import {useEffect,useState,type ReactNode} from 'react';
import {request} from './api';
export default function AuthGate({children}:{children:ReactNode}){
 const [ready,setReady]=useState(false),[required,setRequired]=useState(false),[password,setPassword]=useState(''),[error,setError]=useState(''),[revision,setRevision]=useState(0);
 useEffect(()=>{const login=()=>{setRequired(true);setReady(true);};window.addEventListener('dashboard-login-required',login);return()=>window.removeEventListener('dashboard-login-required',login);},[]);
 useEffect(()=>{const c=new AbortController();request('/api/dashboard/v2/auth/status',{signal:c.signal}).then(p=>{if(!c.signal.aborted){setRequired(p.required&&!p.authenticated);setReady(true);setError('');}}).catch(()=>{if(!c.signal.aborted)setError('연결하지 못했습니다.');});return()=>c.abort();},[revision]);
 if(ready&&!required)return <>{children}</>;
 return <main className="login-page"><form className="panel login-card" onSubmit={async e=>{e.preventDefault();try{await request('/api/dashboard/v2/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password})});setPassword('');setRequired(false);setReady(true);}catch(e){setError(e instanceof Error?e.message:'로그인에 실패했습니다.');}}}><h1>OpenWebUI Analytics</h1>{required?<><label>접속 암호<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required/></label><button className="button primary" type="submit">로그인</button></>:<p>연결 중입니다.</p>}{error&&<p role="alert">{error}</p>}{error&&!required&&<button className="button" type="button" onClick={()=>setRevision(n=>n+1)}>다시 불러오기</button>}</form></main>;
}
