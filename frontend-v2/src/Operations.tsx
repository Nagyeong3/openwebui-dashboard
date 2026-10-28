import {useEffect,useState} from 'react';
import {Check,ChevronDown,Database,FileText,Loader2,Play,RefreshCw,Tags,AlertTriangle} from 'lucide-react';
import {Panel} from './components';
import {number} from './domain';
import {request} from './api';

type Stats=Record<string,number|string>;
type Step={name:'openwebui'|'tokens'|'categories';status:string;started_at:string|null;finished_at:string|null;error:string|null;source_id:string|null;stats:Stats};
type Run={id:string;kind:'quick'|'full'|'classify';status:string;started_at:string;finished_at:string|null;error:string|null;steps:Step[]};
type Source={ready?:boolean;configured:boolean;lastSuccess?:string|null;activeRunId:string|null;users?:number;messages?:number;logs?:number;questions?:number|null;pending?:number|null;classified?:number|null;lastRun?:{status:string;finished_at:string|null;error:string|null}|null};
export type OperationStatus={schemaVersion:1;activeRunId:string|null;runs:Run[];sources:{openwebui:Source;tokens:Source;categories:Source};overlap:{openwebuiDays:number;litellmHours:number}};
const names={openwebui:'OpenWebUI 변경분 수집',tokens:'LiteLLM 토큰 수집',categories:'미처리 질문 자동 분류'};
const statusLabel:Record<string,string>={running:'진행 중',success:'완료',failed:'실패',partial:'일부 미완료',cancelled:'중단됨',interrupted:'중단됨',waiting:'대기',skipped:'건너뜀'};
const kindLabel:Record<string,string>={quick:'변경분 업데이트',full:'전체 재대조',classify:'전체 미처리 분류'};
const date=(s:string|null|undefined)=>s?new Date(s).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'아직 없음';
const n=(v:unknown)=>typeof v==='number'?number(v):'—';
export function validateOperations(value:unknown):asserts value is OperationStatus{
  const p=value as OperationStatus;
  if(!p||p.schemaVersion!==1||!p.sources?.openwebui||!p.sources?.tokens||!p.sources?.categories||!p.overlap||!Array.isArray(p.runs))throw new Error('운영 업데이트 API 형식을 확인하세요. 백엔드도 함께 업데이트해야 합니다.');
  for(const r of p.runs){
    if(!r.id||!(r.kind in kindLabel)||!(r.status in statusLabel)||!Array.isArray(r.steps)||r.steps.length!==3||new Set(r.steps.map(s=>s.name)).size!==3)throw new Error('운영 작업 상태가 올바르지 않습니다.');
    for(const step of r.steps)if(!(step.name in names)||!(step.status in statusLabel)||!step.stats||Object.values(step.stats).some(v=>typeof v==='number'&&(!Number.isFinite(v)||v<0)))throw new Error('운영 단계의 상태나 집계가 올바르지 않습니다.');
  }
  if(p.activeRunId!==null&&!p.runs.some(r=>r.id===p.activeRunId&&r.status==='running'))throw new Error('진행 중인 운영 작업을 찾을 수 없습니다.');
}
function stepText(s:Step){
  const p=s.stats;
  if(s.status==='skipped')return s.error||'이번 작업에서 제외';
  if(s.error)return s.error;
  if(s.name==='openwebui')return s.status==='success'?`신규 질문 ${n(p.newQuestions)}건 · 수정 ${n(p.updatedQuestions)}건 · 삭제 ${n(p.deletedQuestions)}건`:`사용자 ${n(p.usersDone)} / ${n(p.usersTotal)}명 · 조회 메시지 ${n(p.messagesSeen)}건`;
  if(s.name==='tokens')return `조회 ${n(p.scanned)}건 · 별칭 일치 ${n(p.saved)}건 · 제외 ${n(p.skipped)}건`;
  return `처리 ${n(p.processed)} / ${n(p.total)}건 · 모델 요청 ${n(p.calls)}배치${Number(p.unavailable)>0?` · 원본 확인 필요 ${n(p.unavailable)}건`:''}`;
}
export default function Operations({token,revision,onUpdated}:{token:string;revision:number;onUpdated:()=>void}){
  const [data,setData]=useState<OperationStatus>(),[error,setError]=useState(''),[actionError,setActionError]=useState('');
  const [sending,setSending]=useState(false),[tick,setTick]=useState(0),[expanded,setExpanded]=useState<string|null>(null);
  const headers:Record<string,string>=token?{Authorization:'Bearer '+token}:{};
  useEffect(()=>{
    const c=new AbortController();let timer:ReturnType<typeof setTimeout>;let previous:string|null=null;let failures=0;
    async function poll(){
      try{
        const p=await request('/api/dashboard/v2/operations/status',{headers,signal:c.signal});validateOperations(p);
        if(c.signal.aborted)return;
        setData(p);setError('');failures=0;
        if(previous&&!p.activeRunId)onUpdated();
        previous=p.activeRunId;
        if(p.activeRunId||Object.values(p.sources).some(s=>s.activeRunId))timer=setTimeout(poll,3000);
      }catch(e){if(!c.signal.aborted){setError(e instanceof Error?e.message:'운영 상태 조회 실패');if(++failures<=3)timer=setTimeout(poll,5000);}}
    }
    void poll();return()=>{c.abort();clearTimeout(timer);};
  },[token,revision,tick]);
  const active=data?.runs.find(r=>r.id===data.activeRunId),job=active||data?.runs[0];
  const busy=sending||!!active||!!(data&&Object.values(data.sources).some(s=>s.activeRunId));
  async function start(kind:'quick'|'full'|'classify'){
    setSending(true);setActionError('');
    try{await request('/api/dashboard/v2/operations/update?kind='+kind,{method:'POST',headers});setTick(t=>t+1);}
    catch(e){setActionError(e instanceof Error?e.message:'업데이트 시작 실패');}
    finally{setSending(false);}
  }
  async function stop(){
    setSending(true);setActionError('');
    try{await request('/api/dashboard/v2/operations/stop-classification',{method:'POST',headers});setTick(t=>t+1);}
    catch(e){setActionError(e instanceof Error?e.message:'중지 요청 실패');}
    finally{setSending(false);}
  }
  if(!data&&!error)return <div className="live-loading" role="status"><Loader2 className="spinning"/>운영 상태를 불러오는 중입니다.</div>;
  if(!data)return <div className="error-state" role="alert"><h2>운영 업데이트를 불러올 수 없습니다</h2><p>{error}</p></div>;
  const catStep=active?.steps.find(s=>s.name==='categories'&&s.status==='running');
  return <div className="operations-page">
    <div className="operations-actions"><button className="button primary" disabled={busy} onClick={()=>void start('quick')}>{busy?<Loader2 size={16} className="spinning"/>:<RefreshCw size={16}/>}최근 변경분 업데이트</button></div>
    {(error||actionError)&&<p className="live-warning" role="alert">{actionError||error}</p>}
    <div className="operations-sources">
      {(['openwebui','tokens','categories'] as const).map(key=>{
        const s=data.sources[key],Icon=key==='openwebui'?Database:key==='tokens'?FileText:Tags;
        return <article className="metric operations-source" key={key}><span className="operations-icon"><Icon size={23}/></span><div><strong>{key==='openwebui'?'OpenWebUI 데이터':key==='tokens'?'LiteLLM 토큰':'질문 분류'}</strong><span className={'operations-state '+(!s.configured?'warning':s.activeRunId?'running':s.ready||key==='categories'?'success':'waiting')}>{!s.configured?'설정 필요':s.activeRunId?'진행 중':s.ready||key==='categories'?'연결됨':'수집 대기'}</span>{key==='categories'?<><p>미처리 {n(s.pending)}건</p><small>분류 완료 {n(s.classified)}건</small></>:<><p>최근 수집 {date(s.lastSuccess)}</p><small>{key==='openwebui'?`등록 사용자 ${n(s.users)}명`:`저장 로그 ${n(s.logs)}건`}</small></>}</div></article>;
      })}
    </div>
    <Panel title="업데이트 진행" subtitle={job?`${kindLabel[job.kind]} · 시작 ${date(job.started_at)}`:'최근 변경분 업데이트를 실행하면 단계별 진행 상황을 확인할 수 있습니다.'} action={job?<span className={'operations-state '+job.status}>{statusLabel[job.status]}</span>:undefined}>
      <ol className="operations-timeline">{(['openwebui','tokens','categories'] as const).map((name,i)=>{
        const s=job?.steps.find(s=>s.name===name);const state=s?.status||'waiting';
        return <li key={name} className={state}><span className="operations-step-icon">{state==='success'?<Check size={19}/>:state==='running'?<Loader2 size={19} className="spinning"/>:state==='failed'?<AlertTriangle size={18}/>:i+1}</span><div className="operations-step-body"><strong>{names[name]}</strong><p>{s?stepText(s):name==='openwebui'?'마지막 성공 이후 변경된 데이터 조회':name==='tokens'?'LiteLLM 로그와 별칭 기준 사용량 반영':'미처리 질문을 끝까지 자동 분류'}</p>{s?.status==='failed'&&name==='categories'&&typeof s.stats.calls==='number'&&<p>모델 요청 {n(s.stats.calls)}배치 · 처리 {n(s.stats.processed)}건</p>}{s?.started_at&&<small>{date(s.started_at)}{s.finished_at?' — '+date(s.finished_at):''}</small>}{s?.status==='running'&&name!=='categories'&&<div className="operations-indeterminate" aria-label="수집 진행 중"><i/></div>}</div><span className={'operations-state '+state}>{statusLabel[state]}</span></li>;
      })}</ol>
      {catStep&&<div className="operations-classify"><div><strong>질문 분류</strong><p>{n(catStep.stats.processed)} / {n(catStep.stats.total)}건</p></div>{Number(catStep.stats.total)>0?<progress className="category-progress" aria-label="질문 분류 진행률" value={Number(catStep.stats.processed||0)+Number(catStep.stats.unavailable||0)} max={Number(catStep.stats.total)}/>:<span className="muted">대상 확인 중</span>}<button className="button" disabled={sending||!!catStep.stats.stop_requested} onClick={()=>void stop()}>{catStep.stats.stop_requested?'중지 요청됨':'분류 중지'}</button></div>}
      {job?.error&&<p className="live-warning" role="alert">{job.error}</p>}
      {!active&&data.runs[0]?.status==='partial'&&<p className="live-warning">일부 단계가 완료되지 않았습니다. 실패한 단계의 상태를 확인하고 다시 실행하세요. 완료된 데이터는 유지됩니다.</p>}
    </Panel>
    <Panel title="최근 실행 내역"><div className="overview-table-scroll"><table><thead><tr><th>시작 시각</th><th>실행 종류</th><th>데이터 수집</th><th>토큰 수집</th><th>질문 분류</th><th>결과</th><th>상세</th></tr></thead><tbody>{data.runs.map(r=><tr key={r.id}><td>{date(r.started_at)}</td><td>{kindLabel[r.kind]}</td>{r.steps.map(s=><td key={s.name}><span className={'operations-state '+s.status}>{statusLabel[s.status]}</span></td>)}<td><span className={'operations-state '+r.status}>{statusLabel[r.status]}</span></td><td><button className="button" aria-expanded={expanded===r.id} onClick={()=>setExpanded(expanded===r.id?null:r.id)}>보기</button></td></tr>)}</tbody></table>{!data.runs.length&&<p className="muted">아직 실행한 업데이트가 없습니다.</p>}</div>{expanded&&<div className="operations-history-detail">{data.runs.find(r=>r.id===expanded)?.steps.map(s=><p key={s.name}><strong>{names[s.name]}</strong> · {stepText(s)}</p>)}</div>}</Panel>
    <details className="panel operations-advanced"><summary><ChevronDown size={17}/>고급 작업</summary><p className="muted">전체 재대조는 설정된 전체 이력을 다시 조회하므로 오래 걸릴 수 있습니다. 평소에는 최근 변경분 업데이트를 사용하세요.</p><div className="table-controls"><button className="button" disabled={busy} onClick={()=>void start('full')}><RefreshCw size={15}/>전체 재대조</button><button className="button" disabled={busy} onClick={()=>void start('classify')}><Play size={15}/>전체 미처리 분류</button></div></details>
    <p className="live-note">최근 변경분은 마지막 성공 시점부터 조회합니다. 지연 반영을 위해 OpenWebUI {data.overlap.openwebuiDays}일 · LiteLLM {data.overlap.litellmHours}시간을 겹쳐 읽고 중복을 제거합니다.</p>
  </div>;
}
