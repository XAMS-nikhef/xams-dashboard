from __future__ import annotations

import math
import os
from datetime import datetime
from flask import Flask, jsonify, render_template, request, redirect

from backend.deletion_service import delete_run_disk_data
from backend.events_loader import load_event_features
from backend.loadability import check_is_stored, processing_up_to_date, scan_disk_availability
from backend.mongo_service import MongoService
from backend.processing_service import ProcessingService
from backend.config import settings
from backend.submit_queue import SubmitQueue

app = Flask(__name__, template_folder='templates', static_folder='static')

mongo = MongoService()
processing = ProcessingService()
submit_queue = SubmitQueue(settings.queue_file)


def _serialize_dt(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _json_safe(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _json_safe(val) for k, val in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_json_safe(x) for x in v]
    return str(v)


def _is_led_run_doc(doc):
    if not isinstance(doc, dict):
        return False
    mode = str(doc.get("mode") or "").lower()
    xbk = doc.get("xams_bookkeeping") if isinstance(doc.get("xams_bookkeeping"), dict) else {}
    run_class = str(xbk.get("run_class") or "").lower()
    if run_class == "led":
        return True
    if "led" in mode:
        return True
    tags = doc.get("tags") or []
    for t in tags:
        name = (t.get("name") if isinstance(t, dict) else str(t)).lower()
        if "led" in name:
            return True
    return False


@app.get('/')
@app.get('/v2')
def v2_index():
    if request.path == '/v2':
        return redirect('/')
    return render_template('v2/index.html')


@app.get('/admin')
@app.get('/v2/admin')
def v2_admin():
    if request.path == '/v2/admin':
        return redirect('/admin')
    return render_template('v2/admin.html')


@app.get('/corrections')
@app.get('/v2/corrections')
def v2_corrections():
    if request.path == '/v2/corrections':
        return redirect('/corrections')
    return render_template('v2/corrections.html')


@app.get('/api/runs')
@app.get('/api/v2/runs')
def v2_runs():
    page = max(1, int(request.args.get('page', 1)))
    page_size = min(200, max(10, int(request.args.get('page_size', 30))))
    q = (request.args.get('q') or '').strip().lower()
    status = (request.args.get('status') or '').strip().lower()
    science_run_id = (request.args.get('science_run_id') or '').strip()
    run_class = (request.args.get('run_class') or '').strip()
    source_type = (request.args.get('source_type') or '').strip()
    run_mode = (request.args.get('run_mode') or '').strip()
    use_active_sr = (request.args.get('use_active_sr') or '1').strip() != '0'
    if science_run_id.lower() == 'all':
        science_run_id = ''
        use_active_sr = False

    runs, total = mongo.get_runs_page(
        page=page,
        page_size=page_size,
        status=status or None,
        query_text=q or None,
        science_run_id=science_run_id or None,
        run_mode=run_mode or None,
        run_class=run_class or None,
        source_type=source_type or None,
        default_active_sr=use_active_sr,
    )
    condor = mongo.get_condor_runs()
    condor_ok = None not in condor
    queued = submit_queue.queued_run_ids()
    rows = [{
        'run_id': r.number,
        'mode': r.mode or '',
        'status': r.processing_status or 'unknown',
        'has_raw_records': bool(r.has_raw_records),
        'has_event_info': bool(r.has_events),
        'has_led_calibration': bool(r.has_led_calibration),
        'science_run_id': r.science_run_id or '',
        'run_class': r.run_class or '',
        'source_type': r.source_type or '',
        'start': _serialize_dt(r.start),
        'end': _serialize_dt(r.end),
        'corrections': list(r.corrections or []),
        'condor': condor.get(r.number) or '',
        'queued': r.number in queued,
        'stale': (r.processing_status in ('submitted', 'running')
                  and condor_ok and not condor.get(r.number)),
    } for r in runs]

    n_pages = max(1, math.ceil(total / page_size))
    page = min(page, n_pages)
    return jsonify(
        {
            'page': page,
            'page_size': page_size,
            'total': total,
            'n_pages': n_pages,
            'rows': rows,
            'active_science_run': mongo.get_active_science_run(),
        }
    )


@app.get('/api/runs/uptodate')
@app.get('/api/v2/runs/uptodate')
def v2_runs_uptodate():
    """Up-to-date status of event_info for a list of runs (slow: builds lineages; called after the table)."""
    ids = [int(x) for x in (request.args.get('run_ids') or '').split(',') if x.strip().isdigit()][:200]
    docs = mongo.runs.find({'number': {'$in': ids}}, {'number': 1, 'data.type': 1, 'data.corrections_version': 1,
                                                      'data.lineage_hash': 1, '_id': 0})
    out = {}
    for d in docs:
        out[str(d['number'])] = processing_up_to_date(d['number'], d.get('data') or [])
    return jsonify(out)


@app.get('/api/meta')
@app.get('/api/v2/meta')
def v2_meta():
    modes = mongo.runs.distinct("mode")
    modes = sorted([m for m in modes if m])
    return jsonify(
        {
            'active_science_run': mongo.get_active_science_run(),
            'science_runs': mongo.list_science_runs(),
            'run_modes': modes,
            'run_classes': ["science", "calibration", "led", "test"],
            'corrections_versions': processing.list_corrections_versions(),
            'amstrax_default_path': processing.default_amstrax_root,
        }
    )


@app.get('/api/corrections/meta')
@app.get('/api/v2/corrections/meta')
def v2_corrections_meta():
    amstrax_path = (request.args.get('amstrax_path') or '').strip() or None
    return jsonify({
        "amstrax": processing.get_amstrax_info(amstrax_path=amstrax_path),
        "corrections_versions": processing.list_corrections_versions(),
    })


@app.get('/api/corrections/summary')
@app.get('/api/v2/corrections/summary')
def v2_corrections_summary():
    run_id = int(request.args.get('run_id', '0') or '0')
    corrections_version = (request.args.get('corrections_version') or 'ONLINE').strip()
    if run_id <= 0:
        return jsonify({"error": "invalid_run_id"}), 400
    return jsonify(processing.summarize_corrections_for_run(run_id=run_id, corrections_version=corrections_version))


@app.get('/api/run/<int:run_id>')
@app.get('/api/v2/run/<int:run_id>')
def v2_run(run_id: int):
    d = mongo.get_run_details(run_id)
    if d is None:
        return jsonify({'error': 'run_not_found', 'run_id': run_id}), 404
    ps = d.processing_status or {}
    if not isinstance(ps, dict):
        ps = {'status': str(ps)}
    return jsonify({
        'run_id': d.number,
        'mode': d.mode,
        'start': _serialize_dt(d.start),
        'end': _serialize_dt(d.end),
        'tags': _json_safe(d.tags),
        'comments': _json_safe(d.comments),
        'processing_status': _json_safe(ps),
        'raw_doc': _json_safe(d.raw_doc),
    })


@app.get('/api/held-jobs')
@app.get('/api/v2/held-jobs')
def v2_held_jobs():
    return jsonify({'rows': mongo.get_held_jobs()})


@app.get('/api/jobs')
@app.get('/api/v2/jobs')
def v2_jobs():
    return jsonify(mongo.get_queue_jobs(limit=100))


@app.get('/api/run/<int:run_id>/availability')
@app.get('/api/v2/run/<int:run_id>/availability')
def v2_availability(run_id: int):
    return jsonify(scan_disk_availability(run_id))


@app.get('/api/run/<int:run_id>/plot-data')
@app.get('/api/v2/run/<int:run_id>/plot-data')
def v2_plot_data(run_id: int):
    max_points = min(150000, max(5000, int(request.args.get('max_points', 80000))))
    max_peaks = min(400000, max(10000, int(request.args.get('max_peaks', 120000))))
    max_waveforms = min(200, max(1, int(request.args.get('max_waveforms', 40))))
    return jsonify(load_event_features(run_id=run_id, max_points=max_points, max_peaks=max_peaks, max_waveforms=max_waveforms))


@app.get('/api/run/<int:run_id>/job-logs')
@app.get('/api/v2/run/<int:run_id>/job-logs')
def v2_run_job_logs(run_id: int):
    limit = min(12, max(1, int(request.args.get('limit', 6))))
    return jsonify(processing.get_run_job_logs(run_id=run_id, limit=limit))


@app.get('/api/run/<int:run_id>/corrections-compat')
@app.get('/api/v2/run/<int:run_id>/corrections-compat')
def v2_run_corrections_compat(run_id: int):
    return jsonify(processing.list_corrections_compatibility(run_id=run_id))


@app.post('/api/backfill-bookkeeping')
@app.post('/api/v2/backfill-bookkeeping')
def v2_backfill_bookkeeping():
    body = request.get_json(force=True, silent=True) or {}
    science_run_id = (body.get('science_run_id') or '').strip()
    run_class = (body.get('run_class') or '').strip()
    source_type = (body.get('source_type') or '').strip()
    run_id_min = body.get('run_id_min')
    run_id_max = body.get('run_id_max')
    only_missing = bool(body.get('only_missing', True))
    dry_run = bool(body.get('dry_run', True))
    run_ids = body.get('run_ids') or None
    actor = os.getenv("USER", "dashboard")
    result = mongo.backfill_bookkeeping(
        science_run_id=science_run_id,
        run_class=run_class,
        source_type=source_type,
        run_id_min=int(run_id_min) if run_id_min not in (None, '') else None,
        run_id_max=int(run_id_max) if run_id_max not in (None, '') else None,
        run_ids=[int(x) for x in run_ids] if run_ids else None,
        only_missing=only_missing,
        dry_run=dry_run,
        actor=actor,
    )
    return jsonify(result)


def _record_history(run_id, req, result, status, reason):
    """Append the outcome to the run's processing_history (not in dry/off mode)."""
    if processing.submit_mode != 'on':
        return
    mongo.append_processing_history(
        run_id,
        {
            'time': datetime.utcnow(),
            'user': os.getenv("USER", "dashboard"),
            'action': 'submit_offline_reprocess',
            'status': status,
            'reason': reason,
            'targets': req.get('required_targets'),
            'mode': req.get('mode'),
            'corrections_version': req.get('corrections_version'),
            'amstrax_ref': req.get('amstrax_ref'),
            'resource_profile': req.get('resource_profile'),
            'job_name': (result or {}).get('job_name'),
            'returncode': (result or {}).get('returncode'),
            'stderr': ((result or {}).get('stderr') or '')[-1000:],
        },
    )


def _submit_request(req):
    """Submit one prepared request (also used by the waiting-list worker)."""
    run_id = int(req['run_id'])
    condor = mongo.get_condor_runs()
    if condor.get(run_id):
        result = dict(req, submitted=False, status='skipped',
                      reason='a Condor job for this run is already in the queue ({})'.format(condor[run_id]))
        return result
    result = processing.submit_run(
        run_id,
        target=req['targets'],
        corrections_version=req.get('corrections_version'),
        amstrax_ref=req.get('amstrax_ref'),
        resource_profile=req.get('resource_profile') or '8gb',
    )
    result['mode'] = req.get('mode')
    status = result.get('status') or ('submitted' if result.get('submitted') else 'failed')
    if status != 'busy':
        _record_history(run_id, req, result, status, result.get('reason'))
    return result


def _prepare_request(run_id, requested_targets, corrections_version, amstrax_ref, resource_profile):
    """Work out targets for a run; returns (request, skip_result_or_None)."""
    run_details = mongo.get_run_details(run_id)
    run_doc = run_details.raw_doc if run_details and isinstance(run_details.raw_doc, dict) else {}
    is_led = _is_led_run_doc(run_doc)
    targets = ['raw_records', 'records_led', 'led_calibration'] if is_led else [str(t) for t in requested_targets]
    required_targets = ['led_calibration'] if is_led else [str(t) for t in requested_targets]
    availability = scan_disk_availability(run_id)
    # For science runs: if raw_records are not stored in the current context,
    # prepend raw_records so process.py knows to build them from live data first.
    if not is_led and not check_is_stored(run_id, 'raw_records'):
        targets = ['raw_records'] + targets
    req = {
        'run_id': run_id,
        'targets': targets,
        'required_targets': required_targets,
        'mode': 'led' if is_led else 'event',
        'corrections_version': corrections_version,
        'amstrax_ref': amstrax_ref,
        'resource_profile': resource_profile,
    }
    # Skip only when all targets are already stored with the requested corrections version.
    # If amstrax_ref is explicitly requested, always allow re-submit (version/path changes are meaningful).
    if amstrax_ref:
        return req, None
    wanted = str(corrections_version or '')
    done = all(
        any(
            str(r.get('type')) == t and bool(r.get('loadable'))
            and (not wanted or str(r.get('db_corrections_version') or '') == wanted)
            for r in availability
        )
        for t in required_targets
    )
    if not done:
        return req, None
    reason = 'already processed{}: {}'.format(
        ' with corrections ' + wanted if wanted else '', ', '.join(required_targets))
    return req, dict(req, submitted=False, status='skipped', reason=reason)


@app.post('/api/submit')
@app.post('/api/v2/submit')
def v2_submit():
    body = request.get_json(force=True, silent=True) or {}
    run_ids = body.get('run_ids') or []
    requested_targets = body.get('targets') or ['peak_basics', 'event_basics', 'event_positions', 'event_info']
    corrections_version = (body.get('corrections_version') or '').strip() or None
    amstrax_ref = (body.get('amstrax_ref') or '').strip() or None
    resource_profile = (body.get('resource_profile') or '8gb').strip() or '8gb'
    out = []
    # queue_only: the caller already hit the job limit, put runs straight on the waiting list
    busy = bool(body.get('queue_only'))
    for rid in run_ids:
        run_id = int(rid)
        try:
            req, skip = _prepare_request(run_id, requested_targets, corrections_version, amstrax_ref, resource_profile)
        except Exception as e:
            out.append({'run_id': run_id, 'submitted': False, 'status': 'failed', 'reason': str(e)})
            continue
        if skip:
            _record_history(run_id, req, None, 'skipped', skip['reason'])
            out.append(skip)
            continue
        if run_id in submit_queue.queued_run_ids():
            out.append(dict(req, submitted=False, status='queued', reason='already on the waiting list'))
            continue
        # Once the job limit is hit, the remaining runs go straight to the waiting list.
        result = {'status': 'busy'} if busy else _submit_request(req)
        if result.get('status') == 'busy':
            busy = True
            submit_queue.add(req)
            reason = result.get('reason') or 'job limit reached'
            _record_history(run_id, req, result, 'queued', reason)
            result = dict(req, submitted=False, status='queued',
                          reason=reason + '; on the waiting list, submitted automatically when there is room')
        out.append(result)
    counts = {}
    for x in out:
        counts[x.get('status', 'failed')] = counts.get(x.get('status', 'failed'), 0) + 1
    return jsonify({
        'submitted': counts.get('submitted', 0),
        'queued': counts.get('queued', 0),
        'skipped': counts.get('skipped', 0),
        'failed': counts.get('failed', 0),
        'counts': counts,
        'total': len(out),
        'submit_mode': processing.submit_mode,
        'max_jobs': processing.max_jobs,
        'results': _json_safe(out),
    })


@app.get('/api/queue')
@app.get('/api/v2/queue')
def v2_queue():
    st = submit_queue.status()
    st['submit_mode'] = processing.submit_mode
    st['max_jobs'] = processing.max_jobs
    st['interval_s'] = settings.queue_interval_s
    return jsonify(st)


@app.post('/api/queue/remove')
@app.post('/api/v2/queue/remove')
def v2_queue_remove():
    body = request.get_json(force=True, silent=True) or {}
    rid = body.get('run_id')
    n = submit_queue.remove(int(rid) if rid not in (None, '', 'all') else None)
    return jsonify({'removed': n})


@app.post('/api/queue/retry')
@app.post('/api/v2/queue/retry')
def v2_queue_retry():
    results = submit_queue.process_once(_submit_request)
    return jsonify({'results': _json_safe(results), 'queue': submit_queue.status()})


@app.post('/api/run/<int:run_id>/delete_data')
@app.post('/api/v2/run/<int:run_id>/delete_data')
def v2_delete_run_data(run_id: int):
    disk = delete_run_disk_data(run_id)
    db = mongo.delete_run_data_entries(run_id)
    return jsonify({'disk': disk, 'db': db,
                    'n_deleted': len(disk['deleted']),
                    'n_errors': len(disk['errors'])})


if __name__ == '__main__':
    submit_queue.start(_submit_request, interval_s=settings.queue_interval_s)
    host = os.getenv('XAMS_DASH_HOST', '127.0.0.1')
    port = int(os.getenv('XAMS_DASH_PORT', '8070'))
    app.run(host=host, port=port, debug=False)
