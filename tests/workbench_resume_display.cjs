const fs=require('fs'),vm=require('vm'),assert=require('assert');
const path=process.argv[2]||'src/neutral_atom_env/visualization/workbench.js';
const source=fs.readFileSync(path,'utf8');
const helpers=source.slice(source.indexOf('function resumedExecutionText('),source.indexOf('function renderDecisions('));
assert(helpers.includes('function resumedCompileSummary('));
const context={};vm.createContext(context);vm.runInContext(helpers,context);
const result={compile_timing_scope:'suffix_only',compile_seconds:631.276,provenance:{resume:{
 parent_output:'parent-attempt',prefix_completed_gates:1588,prefix_plans:468,
 parent_observed_elapsed_seconds:3579.865288799978,classification:'timeout'}}};
const text=context.resumedCompileSummary(result,47);
for(const wanted of ['后缀续编译 631.28 s','后缀 47 个服务段','1588','468','3579.87 s','parent-attempt','timeout','不代表完整成功编译耗时','完整动画含前缀与后缀','日志仅含后缀'])assert(text.includes(wanted),wanted);
assert(!text.includes('历史编译'));assert(!text.includes('成功编译 4211'));
assert.equal(context.resumedCompileSummary({compile_seconds:631.276},47),'');
assert.equal(context.resumedExecutionText({}),'');
assert(context.resumedCompileSummary({compile_timing_scope:'suffix_only'},0).includes('未记录'));
assert(source.includes("if(next.compile_timing_scope==='suffix_only')$('greedy-summary').textContent="));
assert(source.includes("if(next.provenance&&next.compile_timing_scope==='suffix_only')$('saved-provenance').textContent+="));
console.log('PASS resumed display scope, parent provenance and unchanged ordinary path (pure UI helpers only)');
