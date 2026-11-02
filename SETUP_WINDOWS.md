# Legacy setup guide

This file has been retired in favor of the cross-platform developer workflow in [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).

Use the project as a normal Python application:

```bash
python -m venv .venv
# activate the virtual environment in your shell
pip install -r requirements.txt
python -m caseforge.doctor
python -m caseforge.cli
uvicorn caseforge.api.main:app --reload
```

The old Windows-only startup scripts are no longer the recommended path.
