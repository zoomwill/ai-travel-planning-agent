"""Local CLI for the read-only evidence module also shipped in the API image."""

from app.deployment.chroma_evidence import main

if __name__ == "__main__":
    raise SystemExit(main())
