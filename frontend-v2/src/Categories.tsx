import { useEffect, useRef, useState } from 'react';
import { Loader2, Play, RefreshCw, Tags } from 'lucide-react';
import { request } from './api';
import { Chart, Panel, Select, Modal, palette } from './components';
import { number } from './domain';
import { periodParams, type Query, type Payload } from './live-api';

export type CategorySlice = {name:string;value:number;percent:number};
type Run = {id:string;status:string;processed:number;calls:number;reused:number;unavailable:number;total:number;stop_requested:number;pause_requested:number;chunksDone:number;window_size:number;error:string|null};
type Status = {model?:string;separateModelUrl?:boolean;configured:boolean;configurationError:string|null;batchLimit:number;sampleLimit:number;activeRunId:string|null;pausedRunId?:string|null;runs:Run[]};
type CategoryPayload = {
  schemaVersion:1; source:'category-llm-cache'; period:Payload['period'];
  summary:{questions:number;classified:number;pending:number;uncertain:number;noText:number;truncated:number;coveragePercent:number};
  distribution:CategorySlice[];
  filters:{divisions:string[];teams:string[];positions:string[];categories:string[]};
  definitions:{category:string;description:string}[];
  detail:{total:number;page:number;pageSize:number;records:{id:string;at:number;userName:string;team:string;category:string;state:string;confidence:number|null;manual?:boolean;fallback?:boolean;truncated:boolean}[]};
};
export function validateCategories(value:unknown): asserts value is CategoryPayload {
  const d=value as CategoryPayload;
  if(!d || d.schemaVersion!==1 || d.source!=='category-llm-cache' || !d.period || !d.summary || !d.filters || !Array.isArray(d.distribution) || !Array.isArray(d.detail?.records) || !Array.isArray(d.definitions)) throw new Error('카테고리 API 응답 형식을 확인하세요.');
  for(const n of Object.values(d.summary)) if(typeof n!=='number'||!Number.isFinite(n)||n<0) throw new Error('카테고리 집계 수치가 잘못되었습니다.');
  if(d.summary.questions!==d.summary.classified+d.summary.pending+d.summary.uncertain+d.summary.noText || d.distribution.some(r=>typeof r.name!=='string'||!Number.isInteger(r.value)||r.value<0||!Number.isFinite(r.percent)||r.percent<0||r.percent>100) || d.distribution.reduce((n,r)=>n+r.value,0)!==d.summary.questions) throw new Error('카테고리 합계가 질문 수와 맞지 않습니다.');
}
export function categoryDonut(rows:CategorySlice[], dark:boolean){
  return {color:palette,tooltip:{trigger:'item',valueFormatter:(v:unknown)=>number(Number(v))+'건'},series:[{type:'pie',radius:['43%','66%'],center:['50%','50%'],avoidLabelOverlap:true,label:{show:false},emphasis:{label:{show:true,formatter:'{b}\n{d}%'}},data:rows.map((r,i)=>({...r,itemStyle:{color:palette[i%palette.length]}})).filter(r=>r.value>0)}]};
}
export function CategoryDistribution({rows,dark,table}:{rows:CategorySlice[];dark:boolean;table:boolean}){
  if(table) return <div className="overview-table-scroll"><table><thead><tr><th>카테고리</th><th>질문 수 (건)</th><th>비율 (%)</th></tr></thead><tbody>{rows.map(r=><tr key={r.name}><td>{r.name}</td><td>{number(r.value)}</td><td>{r.percent}%</td></tr>)}</tbody></table></div>;
  if(!rows.some(r=>r.value>0)) return <div className="overview-pending"><Tags size={30}/><strong>선택 기간에 질문이 없습니다</strong></div>;
  return <div className="category-distribution"><Chart height={Math.max(280,rows.length*32)} dark={dark} label="질문 카테고리별 비율" option={categoryDonut(rows,dark)}/><ul className="category-legend" aria-label="카테고리별 질문 수와 비율">{rows.map((r,i)=><li key={r.name}><i style={{background:palette[i%palette.length]}}/><span>{r.name}</span><strong>{number(r.value)}건</strong><small>{r.percent}%</small></li>)}</ul></div>;
}
const stateLabel:Record<string,string>={classified:'분류 완료',pending:'미처리',uncertain:'검토 필요','no-text':'텍스트 없음'};
export default function Categories({q,token,revision,dark,onChange,onPeriod}:{q:Query;token:string;revision:number;dark:boolean;onChange:(p:Partial<Query>)=>void;onPeriod:(p:Payload['period'])=>void}){
  const [category,setCategory]=useState('전체'),[tick,setTick]=useState(0),[table,setTable]=useState(false),[page,setPage]=useState(1);
  const [state,setState]=useState<{key:string;data?:CategoryPayload;error?:string}>({key:''});
  const [status,setStatus]=useState<Status>(),[actionError,setActionError]=useState(''),[starting,setStarting]=useState(false);
  const [reviewId,setReviewId]=useState<string|null>(null),[reviewText,setReviewText]=useState(''),[reviewCategory,setReviewCategory]=useState('기타'),[reviewError,setReviewError]=useState(''),[reviewLoading,setReviewLoading]=useState(false);
  const lastActive=useRef<string|null>(null);
  const headers:Record<string,string>=token?{Authorization:'Bearer '+token}:{};
  const params=periodParams(q);
  for(const key of ['division','team','position'] as const) params.set(key,q[key]);
  params.set('category',category); params.set('page',String(page)); params.set('pageSize','50');
  const key=params.toString()+'|'+revision+'|'+tick+'|'+token;
  useEffect(()=>{
    const c=new AbortController();
    request('/api/dashboard/v2/categories?'+params,{headers,signal:c.signal}).then(p=>{validateCategories(p);if(!c.signal.aborted){const last=Math.max(1,Math.ceil(p.detail.total/50));if(page>last){setPage(last);return;}setState({key,data:p});onPeriod(p.period);}}).catch(e=>{if(!c.signal.aborted)setState({key,error:e instanceof Error?e.message:'분류 현황 조회 실패'});});
    return()=>c.abort();
  },[key]);
  useEffect(()=>{setPage(1);},[q.range,q.start,q.end,q.division,q.team,q.position,category]);
  useEffect(()=>{
    const c=new AbortController();let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try{
        const s=await request('/api/dashboard/v2/categories/status',{headers,signal:c.signal}) as Status;
        if(c.signal.aborted)return;
        setStatus(s);
        if(lastActive.current&&!s.activeRunId)setTick(t=>t+1);
        lastActive.current=s.activeRunId;
        if(s.activeRunId)timer=setTimeout(poll,2000);
      }catch(e){if(!c.signal.aborted)setActionError(e instanceof Error?e.message:'분류 상태 조회 실패');}
    }
    void poll();return()=>{c.abort();clearTimeout(timer);};
  },[token,revision,tick]);
  async function run(kind:'pending'|'sample'|'retry'){
    setStarting(true);setActionError('');
    try{const r=await request('/api/dashboard/v2/categories/classify?kind='+kind,{method:'POST',headers});lastActive.current=r.runId;setTick(t=>t+1);}
    catch(e){setActionError(e instanceof Error?e.message:'분류 시작 실패');}
    finally{setStarting(false);}
  }
  useEffect(()=>{
    if(!reviewId)return;
    const c=new AbortController();setReviewLoading(true);setReviewText('');setReviewError('');
    request('/api/dashboard/v2/categories/question?messageId='+encodeURIComponent(reviewId),{headers,signal:c.signal}).then(p=>{if(!c.signal.aborted){setReviewText(p.text+(p.truncated?'\n…':''));setReviewLoading(false);}}).catch(e=>{if(!c.signal.aborted){setReviewError(e instanceof Error?e.message:'조회하지 못했습니다.');setReviewLoading(false);}});
    return()=>c.abort();
  },[reviewId]);
  async function control(action:'pause'|'stop'|'resume',id?:string){
    setStarting(true);setActionError('');
    try{await request('/api/dashboard/v2/categories/'+action+(id?'?runId='+encodeURIComponent(id):''),{method:'POST',headers});setTick(t=>t+1);}
    catch(e){setActionError(e instanceof Error?e.message:'작업을 처리하지 못했습니다.');}finally{setStarting(false);}
  }
  const data=state.key===key?state.data:undefined,error=state.key===key?state.error:undefined;
  const busy=starting||!!status?.activeRunId||!!status?.pausedRunId,latest=status?.runs[0];
  return <div>
    <Panel title="질문 분류">
      <div className="table-toolbar"><div className="table-controls">
        <button className="button primary" disabled={busy||!status?.configured} onClick={()=>void run('pending')}>{busy?<Loader2 size={16} className="spinning"/>:<Play size={16}/>} {status?.activeRunId?'분류 중':'분류 시작'}</button>
        <button className="button" disabled={busy||!status?.configured} onClick={()=>void run('sample')}><Play size={15}/>{status?.sampleLimit??20}개 먼저 분류</button>
        {status?.activeRunId&&<><button className="button" disabled={starting||!!latest?.pause_requested||!!latest?.stop_requested} onClick={()=>void control('pause')}>{latest?.pause_requested?'일시 중단 중':'일시 중단'}</button><button className="button" disabled={starting||!!latest?.stop_requested} onClick={()=>void control('stop')}>{latest?.stop_requested?'중단 중':'중단'}</button></>}
        {(status?.pausedRunId||latest?.status==='interrupted')&&<><button className="button primary" disabled={starting} onClick={()=>void control('resume',status?.pausedRunId||latest?.id)}>계속하기</button><button className="button" disabled={starting} onClick={()=>void control('stop')}>중단</button></>}

      </div></div>


      {status&&!status.configured&&<p className="live-warning">{status.configurationError}</p>}
      {latest&&<p role="status" className="live-note">{latest.status==='paused'?'일시 중단':latest.status==='running'?'진행 중':latest.status==='success'?'완료':latest.status==='partial'?'일부 미완료':['interrupted','cancelled'].includes(latest.status)?'중단됨':'실패'} · 처리 {number(latest.processed)} / {number(latest.total)}건 {latest.unavailable>0?`· 원본 확인 필요 ${latest.unavailable}건`:''}</p>}
      {latest&&latest.total>0&&<progress className="category-progress" aria-label="전체 질문 분류 진행률" value={latest.processed+latest.unavailable} max={latest.total}/> }
      {(actionError||latest?.error)&&<p className="live-warning" role="alert">{actionError||latest?.error}</p>}
    </Panel>
    {error?<div className="error-state" role="alert"><h2>질문 분류 현황을 불러올 수 없습니다</h2><p>{error}</p></div>:!data?<div className="live-loading"><Loader2 className="spinning"/>분류 현황을 불러오는 중입니다.</div>:<>
      <section className="filters live-filters" aria-label="카테고리 조회 필터">
        <Select label="실" value={q.division} values={data.filters.divisions} onChange={division=>onChange({division,team:'전체'})}/>
        <Select label="팀" value={q.team} values={data.filters.teams} onChange={team=>onChange({team})}/>
        <Select label="직급" value={q.position} values={data.filters.positions} onChange={position=>onChange({position})}/>
        <Select label="카테고리" value={category} values={data.filters.categories} onChange={setCategory}/>
      </section>
      <div className="token-primary">{[['전체 질문 (건)',number(data.summary.questions)],['분류 완료 (건)',number(data.summary.classified)],['미처리 (건)',number(data.summary.pending)],['분류율 (%)',data.summary.coveragePercent+'%']].map(([label,v])=><article className="metric" key={label}><div className="metric-top">{label}</div><strong className="pending-value">{v}</strong></article>)}</div>
      <div className="category-charts">
        <Panel title="질문 카테고리 분포" subtitle="선택 기간·조직의 전체 질문 기준">
          <CategoryDistribution rows={data.distribution} dark={dark} table={table}/>
          <div className="overview-panel-footer"><span>미분류 {number(data.summary.pending+data.summary.uncertain+data.summary.noText)}건</span><div className="table-controls"><button className={'button '+(table?'primary':'')} onClick={()=>setTable(true)} aria-pressed={table}>표</button><button className={'button '+(!table?'primary':'')} onClick={()=>setTable(false)} aria-pressed={!table}>그래프</button></div></div>
        </Panel>
        <details className="panel category-criteria"><summary>분류 기준</summary><div className="category-definitions">{data.definitions.map(d=><article key={d.category}><strong>{d.category}</strong><p className="muted">{d.description.split('.')[0]}.</p></article>)}</div></details>
      </div>
      <Panel title="질문별 분류 결과" action={<button className="button" onClick={()=>setCategory(category==='기타'?'전체':'기타')}>{category==='기타'?'전체 보기':'기타만 보기'}</button>}><div className="overview-table-scroll"><table><thead><tr><th>질문 시각</th><th>사용자</th><th>팀</th><th>카테고리</th><th>처리 상태</th><th>확인</th></tr></thead><tbody>{data.detail.records.map(r=><tr key={r.id}><td>{new Date(r.at*1000).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})}</td><td>{r.userName}</td><td>{r.team}</td><td>{r.category}</td><td>{r.manual?'직접 수정':r.fallback?'기타':stateLabel[r.state]||r.state}{r.truncated?' · 일부 텍스트':''}</td><td><button className="button" onClick={()=>{setReviewCategory(r.category==='미분류'?'기타':r.category);setReviewId(r.id);}}>확인·수정</button></td></tr>)}</tbody></table>{!data.detail.records.length&&<p className="muted">선택 조건의 질문이 없습니다.</p>}</div><div className="table-footer"><span>전체 {number(data.detail.total)}건</span><div className="table-controls"><button className="button" disabled={page<=1} onClick={()=>setPage(p=>p-1)}>이전</button><span>{page} / {Math.max(1,Math.ceil(data.detail.total/50))}</span><button className="button" disabled={page*50>=data.detail.total} onClick={()=>setPage(p=>p+1)}>다음</button></div></div></Panel>
    </>}
    {reviewId&&data&&<Modal title="질문 확인" onClose={()=>setReviewId(null)}><div className="question-review">{reviewLoading?<p>불러오는 중입니다.</p>:<pre>{reviewText||'텍스트가 없습니다.'}</pre>}{reviewError&&<p role="alert">{reviewError}</p>}<Select label="카테고리" value={reviewCategory} values={data.definitions.map(d=>d.category)} onChange={setReviewCategory}/><button className="button primary" disabled={reviewLoading||!!reviewError} onClick={async()=>{try{await request('/api/dashboard/v2/categories/correction',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({messageId:reviewId,category:reviewCategory})});setReviewId(null);setTick(t=>t+1);}catch(e){setReviewError(e instanceof Error?e.message:'저장하지 못했습니다.');}}}>저장</button></div></Modal>}
  </div>;
}
