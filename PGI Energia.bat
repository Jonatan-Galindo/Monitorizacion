@echo off
cd /d C:\PGI_APP_ENERGIA
call .venv\Scripts\activate
streamlit run app.py --server.port 8503
pause