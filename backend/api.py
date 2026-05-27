from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, request

from .loadability import scan_disk_availability
from .mongo_service import MongoService
from .processing_service import ProcessingService


def _json_default(v: Any):
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def create_api_blueprint(mongo: MongoService, processing: ProcessingService) -> Blueprint:
    bp = Blueprint("api", __name__, url_prefix="/api")

    @bp.get("/runs")
    def get_runs():
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 25))
        status = request.args.get("status")
        rows = [asdict(r) for r in mongo.get_runs(page=page, page_size=page_size, status=status)]
        return jsonify(rows)

    @bp.get("/runs/<int:run_id>")
    def get_run_details(run_id: int):
        d = mongo.get_run_details(run_id)
        if d is None:
            return jsonify({"error": "run_not_found", "run_id": run_id}), 404
        payload = asdict(d)
        return jsonify(payload)

    @bp.get("/runs/<int:run_id>/loadability")
    def get_loadability(run_id: int):
        return jsonify(scan_disk_availability(run_id))

    @bp.post("/process")
    def process_run():
        body = request.get_json(force=True, silent=True) or {}
        run_id = int(body.get("run_id"))
        target = str(body.get("target", "events"))
        out = processing.submit_run(run_id=run_id, target=target)
        return jsonify(out), (200 if out["submitted"] else 500)

    @bp.get("/jobs/<int:run_id>")
    def job_status(run_id: int):
        return jsonify(mongo.get_job_status(run_id))

    @bp.post("/runs/<int:run_id>/delete_data")
    def delete_run_data(run_id: int):
        from .deletion_service import delete_run_disk_data

        disk = delete_run_disk_data(run_id)
        db = mongo.delete_run_data_entries(run_id)
        n_deleted = len(disk["deleted"])
        n_errors = len(disk["errors"])
        return jsonify({"disk": disk, "db": db, "n_deleted": n_deleted, "n_errors": n_errors})

    return bp
