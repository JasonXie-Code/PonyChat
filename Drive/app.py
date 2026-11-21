from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

app = FastAPI(title='PonyChat Drive', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['https://drive.ponychat.org', 'https://www.ponychat.org', 'https://ponychat.org'],
    allow_methods=['GET', 'POST', 'OPTIONS'],
    allow_headers=['Authorization', 'Content-Type'],
)


@app.get('/api/drive/health')
@app.get('/healthz')
async def health():
    return {'status': 'running', 'service': 'ponychat-drive', 'storage': 'server-usa'}


app.include_router(router)
