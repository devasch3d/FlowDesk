export type User = {id:number;username:string;email:string;created_at:string};
export class ApiError extends Error {
 constructor(public status:number,message:string){super(message);}
}
export async function request(path:string,method='GET',body?:unknown,extraHeaders:Record<string,string>={}){
 const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),15000);
 try {
  const response=await fetch(`/api${path}`,{method,credentials:'same-origin',signal:controller.signal,headers:{'Content-Type':'application/json','X-FlowDesk-Token':document.querySelector<HTMLMetaElement>('meta[name=flowdesk-token]')?.content||'',...extraHeaders},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){let data;try{data=await response.json();}catch{}throw new ApiError(response.status,data?.detail||`操作失败（${response.status}）`);}
  return response.status===204?null:await response.json();
 }catch(e){if(e instanceof TypeError || (e instanceof DOMException && e.name==='AbortError'))throw new Error('无法连接本地服务，请检查 FlowDesk 启动窗口是否仍在运行，再重试。');throw e;}
 finally{clearTimeout(timer);}
}
