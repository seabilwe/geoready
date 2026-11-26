# Runs

Each run writes `runs/<run_id>/` (date, scenario and a hash of the config and input checksums). `run.json` holds the run record: model version, parameters, input checksums, software versions, timestamps, the QA report and the output manifest. Run folders are not committed.
