"""Optional password login using HttpOnly cookies. Existing Bearer clients remain supported."""
import hashlib,hmac,secrets,time
from fastapi import Request,Response,HTTPException
from pydantic import BaseModel,Field
COOKIE='oui_dashboard_session'

def valid_cookie(settings,value):
    try:
        expiry,nonce,signature=value.split('.')
        payload=expiry+'.'+nonce
        return int(expiry)>time.time() and hmac.compare_digest(signature,hmac.new(settings.dashboard_token.encode(),payload.encode(),hashlib.sha256).hexdigest())
    except (ValueError,AttributeError):
        return False

class Login(BaseModel):
    password:str=Field(max_length=4096)

def attach(app,settings):
    attempts={}
    @app.get('/api/dashboard/v2/auth/status')
    def status(request:Request):
        return {'required':bool(settings.dashboard_token),'authenticated':not settings.dashboard_token or valid_cookie(settings,request.cookies.get(COOKIE))}
    @app.post('/api/dashboard/v2/auth/login')
    def login(body:Login,request:Request,response:Response):
        identity=request.client.host if request.client else 'local'
        now=time.time()
        # Bound per-process state and reject rapid password guessing.
        for ip in list(attempts):
            attempts[ip]=[t for t in attempts[ip] if now-t<60]
            if not attempts[ip]:
                del attempts[ip]
        if len(attempts.get(identity,[]))>=10:
            raise HTTPException(429,'잠시 후 다시 시도하세요.')
        if settings.dashboard_token and not hmac.compare_digest(body.password.encode(),settings.dashboard_token.encode()):
            attempts.setdefault(identity,[]).append(now)
            raise HTTPException(401,'접속 암호를 확인하세요.')
        attempts.pop(identity,None)
        payload=str(int(now)+8*3600)+'.'+secrets.token_hex(16)
        signature=hmac.new(settings.dashboard_token.encode(),payload.encode(),hashlib.sha256).hexdigest()
        response.set_cookie(COOKIE,payload+'.'+signature,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=8*3600,path='/')
        response.headers['Cache-Control']='no-store'
        return {'ok':True}
