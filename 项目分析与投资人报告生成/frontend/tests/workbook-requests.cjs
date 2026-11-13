// Exercise request binding and lost-response handling without a network or browser.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');

const source = fs.readFileSync('frontend/assets/console.js', 'utf8');
const functions = source.slice(source.indexOf('  function workbookRequestId()'), source.indexOf('  function startAuxiliaryPolling('));
const runtime = {};
const bodies = [];
let loseResponse = true;
const job = {
  job_id:'aux_' + 'a'.repeat(32), candidate_tags:['新标签'],
  context_fingerprint:'context-version', tag_group_fingerprint:'refreshed-group'
};
const conversation = {taskId:'task_test', auxiliaryJobs:[job]};
const context = vm.createContext({
  crypto:{getRandomValues:values => webcrypto.getRandomValues(values)}, AbortSignal,
  runtimeOf:() => runtime, renderWorkbookStatus:() => {}, saveState:() => {}, startAuxiliaryPolling:() => {},
  getApiBase:() => 'http://offline.invalid',
  fetch:async (_url, options) => {
    bodies.push(JSON.parse(options.body));
    if (loseResponse) { loseResponse = false; throw new TypeError('Lost response'); }
    return {ok:true, status:202, json:async () => job};
  }
});
vm.runInContext(`${functions}\nglobalThis.request = requestWorkbook; globalThis.makeId = workbookRequestId;`, context);

(async () => {
  await context.request(conversation, ['新标签']);
  assert.equal(runtime.auxiliarySubmitting, false);
  assert.equal(runtime.auxiliaryError, 'Lost response');
  await context.request(conversation, ['新标签']);
  assert.deepEqual(bodies[1], bodies[0]);
  assert.equal(bodies[1].source_job_id, job.job_id);
  assert.equal(bodies[1].expected_context_fingerprint, job.context_fingerprint);
  assert.equal(bodies[1].expected_tag_group_fingerprint, job.tag_group_fingerprint);
  assert.match(bodies[1].client_request_id, /^[A-Za-z0-9_-]{8,80}$/);
  await context.request(conversation, ['新标签']);
  assert.notEqual(bodies[2].client_request_id, bodies[1].client_request_id);
  await context.request(conversation, undefined, true);
  assert.equal(bodies[3].refresh_tags, true);
  assert.equal(bodies[3].source_job_id, undefined);
  context.crypto = undefined;
  assert.match(context.makeId(), /^[A-Za-z0-9_-]{8,80}$/);
  console.log(JSON.stringify({passed:true,refreshedGroupBinding:true,lostResponseIdempotent:true,withoutRandomUUID:true}));
})().catch(error => { console.error(error); process.exitCode = 1; });
