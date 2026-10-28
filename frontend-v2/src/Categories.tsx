import { useEffect, useRef, useState } from 'react';
import { Loader2, Play, RefreshCw, Tags } from 'lucide-react';
import { request } from './api';
import { Chart, Panel, Select, palette } from './components';
import { number } from './domain';
import { periodParams, type Query, type Payload } from './live-api';

export type CategorySlice = {name:string;value:number;percent:number};
type Run = {id:string;status:string;processed:number;calls:number;reused:number;unavailable:number;error:string|null};
type Status = {configured:boolean;configurationError:string|null;batchLimit:number;activeRunId:string|null;runs:Run[]};
type CategoryPayload = {
  schemaVersion:1; source:'category-llm-cache'; period:Payload['period'];
  summary:{questions:number;classified:number;pending:number;uncertain:number;noText:number;truncated:number;coveragePercent:number};
  distribution:CategorySlice[];
  filters:{divisions:string[];teams:string[];positions:string[];categories:string[]};
  definitions:{category:string;description:string}[];
  detail:{total:number;page:number;pageSize:number;records:{id:string;at:number;userName:string;team:string;category:string;state:string;confidence:number|null;truncated:boolean}[]};
};
export function validateCategories(value:unknown): asserts value is CategoryPayload {
  const d=value as CategoryPayload;
  if(!d || d.schemaVersion!==1 || d.source!=='category-llm-cache' || !d.period || !d.summary || !d.filters || !Array.isArray(d.distribution) || !Array.isArray(d.detail?.records) || !Array.isArray(d.definitions)) throw new Error('카테고리 API 응답 형식을 확인하세요.');
  for(const n of Object.values(d.summary)) if(typeof n!=='number'||!Number.isFinite(n)||n<0) throw new Error('카테고리 집계 수치가 잘못되었습니다.');
  if(d.summary.questions!==d.summary.classified+d.summary.pending+d.summary.uncertain+d.summary.noText || d.distribution.some(r=>typeof r.name!=='string'||!Number.isInteger(r.value)||r.value<0||!Number.isFinite(r.percent)||r.percent<0||r.percent>100) || d.distribution.reduce((n,r)=>n+r.value,0)!==d.summary.questions) throw new Error('카테고리 합계가 질문 수와 맞지 않습니다.');
}
export function categoryDonut(rows:CategorySlice[], dark:boolean){
  return {color:palette,tooltip:{trigger:'item',valueFormatter:(v:unknown)=>number(Number(v))+'건'},legend:{type:'scroll',bottom:0,textStyle:{color:dark?'#c0c2d4':'#626980'}},series:[{type:'pie',radius:['43%','66%'],center:['50%','44%'],avoidLabelOverlap:true,label:{show:false},emphasis:{label:{show:true,formatter:'{b}\n{d}%'}},data:rows.filter(r=>r.value>0)}]};
}
export function CategoryDistribution({rows,dark,table}:{rows:CategorySlice[];dark:boolean;table:boolean}){
  if(table) return <div className="overview-table-scroll"><table><thead><tr><th>카테고리</th><th>질문 수 (건)</th><th>비율 (%)</th></tr></thead><tbody>{rows.map(r=><tr key={r.name}><td>{r.name}</td><td>{number(r.value)}</td><td>{r.percent}%</td></tr>)}</tbody></table></div>;
  if(!rows.some(r=>r.value>0)) return <div className="overview-pending"><Tags size={30}/><strong>선택 기간에 질문이 없습니다</strong></div>;
  return <Chart height={300} dark={dark} label="질문 카테고리별 비율" option={categoryDonut(rows,dark)}/>;
}
const stateLabel:Record<string,string>={classified:'분류 완료',pending:'미처리',uncertain:'검토 필요','no-text':'텍스트 없음'};
export default function Categories({q,token,revision,dark,onChange,onPeriod}:{q:Query;token:string;revision:number;dark:boolean;onChange:(p:Partial<Query>)=>void;onPeriod:(p:Payload['period'])=>void}){
  const [category,setCategory]=useState('전체'),[tick,setTick]=useState(0),[table,setTable]=useState(false),[page,setPage]=useState(1);
  const [state,setState]=useState<{key:string;data?:CategoryPayload;error?:string}>({key:''});
  const [status,setStatus]=useState<Status>(),[actionError,setActionError]=useState(''),[starting,setStarting]=useState(false);
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
  async function run(kind:'pending'|'retry'){
    setStarting(true);setActionError('');
    try{const r=await request('/api/dashboard/v2/categories/classify?kind='+kind,{method:'POST',headers});lastActive.current=r.runId;setTick(t=>t+1);}
    catch(e){setActionError(e instanceof Error?e.message:'분류 시작 실패');}
    finally{setStarting(false);}
  }
  const data=state.key===key?state.data:undefined,error=state.key===key?state.error:undefined;
  const busy=starting||!!status?.activeRunId,latest=status?.runs[0];
  return <div>
    <Panel title="질문 분류" subtitle="CSV 정의와 질문 의도를 기준으로 분류합니다.">
      <div className="table-toolbar"><div className="table-controls">
        <button className="button primary" disabled={busy||!status?.configured} onClick={()=>void run('pending')}>{busy?<Loader2 size={16} className="spinning"/>:<Play size={16}/>} {busy?'분류 중':`미처리 질문 분류 · 최대 ${status?.batchLimit??200}개`}</button>
        <button className="button" disabled={busy||!status?.configured} onClick={()=>void run('retry')}><RefreshCw size={15}/>검토 필요 재시도</button>
      </div></div>
      <p className="live-note">분류 작업은 전체 기간의 미처리 질문을 최근순으로 처리합니다. 아래 기간·조직 필터는 조회에 적용됩니다.</p>
      {status&&!status.configured&&<p className="live-warning">{status.configurationError} · 서버 .env 설정 후 재시작하세요.</p>}
      {latest&&<p role="status" className="live-note">{latest.status==='running'?'진행 중':latest.status==='success'?'완료':latest.status==='interrupted'?'중단됨':'실패'} · 처리 {number(latest.processed)}건 · 모델 호출 {number(latest.calls)}회 · 결과 재사용 {number(latest.reused)}건 {latest.unavailable>0?`· 원본 확인 필요 ${latest.unavailable}건`:''}</p>}
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
      <div className="live-charts">
        <Panel title="질문 카테고리 분포" subtitle="선택 기간·조직의 전체 질문 기준">
          <CategoryDistribution rows={data.distribution} dark={dark} table={table}/>
          <div className="overview-panel-footer"><span>미분류 {number(data.summary.pending+data.summary.uncertain+data.summary.noText)}건</span><div className="table-controls"><button className={'button '+(table?'primary':'')} onClick={()=>setTable(true)} aria-pressed={table}>표</button><button className={'button '+(!table?'primary':'')} onClick={()=>setTable(false)} aria-pressed={!table}>그래프</button></div></div>
        </Panel>
        <Panel title="분류 기준"><div className="category-definitions">{data.definitions.map(d=><article key={d.category}><strong>{d.category}</strong><p className="muted">{d.description}</p></article>)}</div><p className="live-note">검토 필요 {number(data.summary.uncertain)}건 · 텍스트 없음 {number(data.summary.noText)}건 · 긴 질문 일부 사용 {number(data.summary.truncated)}건</p></Panel>
      </div>
      <Panel title="질문별 분류 결과" subtitle="질문 원문은 저장하거나 표시하지 않습니다."><div className="overview-table-scroll"><table><thead><tr><th>질문 시각</th><th>사용자</th><th>팀</th><th>카테고리</th><th>처리 상태</th><th>모델 판단 점수</th></tr></thead><tbody>{data.detail.records.map(r=><tr key={r.id}><td>{new Date(r.at*1000).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})}</td><td>{r.userName}</td><td>{r.team}</td><td>{r.category}</td><td>{stateLabel[r.state]||r.state}{r.truncated?' · 일부 텍스트':''}</td><td>{r.confidence===null?'—':r.confidence.toFixed(2)}</td></tr>)}</tbody></table>{!data.detail.records.length&&<p className="muted">선택 조건의 질문이 없습니다.</p>}</div><div className="table-footer"><span>전체 {number(data.detail.total)}건</span><div className="table-controls"><button className="button" disabled={page<=1} onClick={()=>setPage(p=>p-1)}>이전</button><span>{page} / {Math.max(1,Math.ceil(data.detail.total/50))}</span><button className="button" disabled={page*50>=data.detail.total} onClick={()=>setPage(p=>p+1)}>다음</button></div></div></Panel>
    </>}
  </div>;
}
