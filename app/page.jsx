import {readFileSync,readdirSync} from "node:fs";
import path from "node:path";
import Workbench from "./workbench";
import { evolvePath } from "./paths";
const read = file => JSON.parse(readFileSync(file,"utf8"));
export default function Page() {
  const root = path.join(process.cwd(),"public","evidence");
  const runs = [];
  for (const project of readdirSync(root)) {
    for (const id of readdirSync(path.join(root,project)).filter(id=>!id.startsWith("."))) {
      const folder = path.join(root,project,id);
      const report = read(path.join(folder,"report.json"));
      const csv = readFileSync(path.join(folder,"input.csv"),"utf8").trim().split("\n");
      runs.push({report, order:read(path.join(folder,"work-order.json")), context:read(path.join(folder,"context.json")),
        points:csv.slice(1).map(line=>line.split(",").map(Number)),
        output:report.status==="verified"?read(path.join(folder,"output.json")):null,
        generation:report.source_revision?read(path.join(folder,"generation.json")):null,
        folder:evolvePath("/evidence/"+project+"/"+id)});
    }
  }
  return <Workbench runs={runs.sort((a,b)=>b.report.created_utc.localeCompare(a.report.created_utc))}/>;
}
