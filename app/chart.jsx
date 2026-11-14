"use client";
import {useEffect,useRef,useState} from "react";
export default function Chart({run}) {
  const ref=useRef(null);
  const [hover,setHover]=useState(null);
  const {points,output,report}=run;
  const cw=report.project==="linewidth";
  const unit=cw?"mT":"K", yLabel=cw?"Derivative signal (a.u.)":"Integrated intensity (a.u.)";
  useEffect(()=>{
    const canvas=ref.current;
    const draw=()=>{
      const width=canvas.clientWidth,height=canvas.clientHeight, dpr=window.devicePixelRatio||1;
      if(!width || !height)return;
      canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
      const ctx=canvas.getContext("2d");ctx.scale(dpr,dpr);
      const l=41,r=14,t=12,b=29,W=width-l-r,H=height-t-b;
      const [xmin,xmax]=[points[0][0],points.at(-1)[0]];
      const ymin=cw?-0.75:0,ymax=cw?0.75:Math.ceil(Math.max(...points.map(p=>p[1])));
      const x=v=>l+W*(v-xmin)/(xmax-xmin),y=v=>t+H*(ymax-v)/(ymax-ymin);
      ctx.font="10px ui-monospace, monospace";ctx.lineWidth=1;ctx.fillStyle="#a9bac1";
      for(let i=0;i<=4;i++){
        const yy=ymin+(ymax-ymin)*i/4;
        ctx.strokeStyle="#2b3942";ctx.beginPath();ctx.moveTo(l,y(yy));ctx.lineTo(width-r,y(yy));ctx.stroke();
        ctx.textAlign="right";ctx.fillText(Number(yy.toFixed(2)).toString(),l-8,y(yy)+3);
      }
      for(let i=0;i<=4;i++){
        const xx=xmin+(xmax-xmin)*i/4;
        ctx.strokeStyle="#26363e";ctx.beginPath();ctx.moveTo(x(xx),t);ctx.lineTo(x(xx),height-b);ctx.stroke();
        ctx.textAlign="center";ctx.fillText(Number(xx.toFixed(1)).toString(),x(xx),height-9);
      }
      const series=cw?points:Array.from({length:170},(_,i)=>{const xx=xmin+(xmax-xmin)*i/169;return [xx,output.coefficient_au_K/xx+output.background_au]});
      function trace(){ctx.beginPath();series.forEach(([xx,yy],i)=>{if(i)ctx.lineTo(x(xx),y(yy));else ctx.moveTo(x(xx),y(yy))})}
      trace();ctx.lineTo(x(xmax),y(cw?0:ymin));ctx.lineTo(x(xmin),y(cw?0:ymin));ctx.closePath();
      const fill=ctx.createLinearGradient(0,t,0,height);fill.addColorStop(0,"#53e2bb34");fill.addColorStop(1,"#53e2bb08");ctx.fillStyle=fill;ctx.fill();
      trace();ctx.strokeStyle="#69efc5";ctx.lineWidth=2.4;ctx.stroke();
      const markers=cw?points.filter(p=>Math.abs(p[0]-output.peak_mT)<0.0001||Math.abs(p[0]-output.trough_mT)<0.0001):points;
      for(const [xx,yy] of markers){ctx.beginPath();ctx.arc(x(xx),y(yy),3.6,0,2*Math.PI);ctx.fillStyle="#14252d";ctx.fill();ctx.strokeStyle="#adffe3";ctx.lineWidth=1.8;ctx.stroke()}
      if(hover!==null){const p=points[Math.max(0,Math.min(points.length-1,hover))];ctx.setLineDash([3,4]);ctx.strokeStyle="#a4b9be";ctx.beginPath();ctx.moveTo(x(p[0]),t);ctx.lineTo(x(p[0]),height-b);ctx.stroke();ctx.setLineDash([]);
        ctx.fillStyle="#fff";ctx.beginPath();ctx.arc(x(p[0]),y(p[1]),3.3,0,7);ctx.fill();}
    };
    const ob=new ResizeObserver(draw);ob.observe(canvas);draw();return ()=>ob.disconnect();
  },[points,output,cw,hover]);
  return <div className="plot"><div className="plotLegend"><span>{yLabel}</span><span><i/>{cw?"Derivative":"Curie fit"}</span></div>
    <canvas ref={ref} role="img" aria-label={cw?"Analytic Gaussian derivative with marked maximum and minimum":"Integrated intensities plotted against temperature with the fitted Curie curve"} onPointerLeave={()=>setHover(null)} onPointerMove={e=>{
      const box=e.currentTarget.getBoundingClientRect();
      const fraction=Math.max(0,Math.min(1,(e.clientX-box.left-41)/(box.width-55)));
      const value=points[0][0]+fraction*(points.at(-1)[0]-points[0][0]);
      setHover(points.reduce((best,p,i)=>Math.abs(p[0]-value)<Math.abs(points[best][0]-value)?i:best,0));}}/>
    <div className="axis">{hover!==null && points[hover]?points[hover][0]+" "+unit+" · "+points[hover][1].toFixed(4)+" a.u.":cw?"Magnetic field (mT)":"Temperature (K)"}</div></div>
}
