"""SciLifeLab Serve entry-point shim (see docs/deployment.md).

SciLifeLab Serve expects the main Streamlit script to be named ``app.py``
in the image working directory.  ``streamlit_app/streamlit_app.py``
remains the single source of truth for the application; this shim only
redirects the entry point so local development, tests, and the container
all run the identical module.

Run locally with::

    streamlit run app.py
"""

from streamlit_app.streamlit_app import main

if __name__ == "__main__":
    main()