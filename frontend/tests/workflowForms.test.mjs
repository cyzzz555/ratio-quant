import test from 'node:test';
import assert from 'node:assert/strict';
import {backtestDefaults,riskDefaults,backtestFields,riskFields,backtestBody,riskBody} from '../src/workflowForms.ts';

test('each research parameter remains accessible in either view',()=>{
  const keys=backtestFields.map(f=>f.key);
  assert.equal(new Set(keys).size,keys.length);
  assert.deepEqual([...keys,'timeframe'].sort(),Object.keys(backtestDefaults).sort());
  assert.deepEqual(backtestFields.filter(f=>f.simple).map(f=>f.key),['initial_equity','risk_pct']);
});
test('risk inputs retain principal and high water equity, with flows and exposure available',()=>{
  const keys=riskFields.map(f=>f.key);
  assert.equal(new Set(keys).size,keys.length);
  assert.deepEqual([...keys,'mode','direction'].sort(),Object.keys(riskDefaults).sort());
  assert.ok(riskFields.find(f=>f.key==='principal').simple);
  assert.ok(riskFields.find(f=>f.key==='peak').simple);
  for(const key of ['net_flows','existing_notional','pending_notional','step','tick'])assert.ok(keys.includes(key));
});
test('research request preserves all edited costs and Decimal precision, converting only integer windows',()=>{
  const params={...backtestDefaults,fee_bps:'7.125',slippage_bps:'3.5',initial_equity:'1000.0000000000000001',fast_window:'8',slow_window:'16'};
  const before={...params};
  const body=backtestBody(params,'88825a16-6364-4549-ad72-478c7f02cfd7');
  for(const [key,value] of Object.entries(params))assert.equal(body[key],backtestFields.find(f=>f.key===key)?.integer?Number(value):value);
  assert.deepEqual(params,before);
  assert.equal(body.dataset_id,'88825a16-6364-4549-ad72-478c7f02cfd7');
  assert.equal(body.status,undefined);
  assert.equal(body.view_mode,undefined);
});
test('risk request preserves accounting and existing exposure without granting approval',()=>{
  const form={...riskDefaults,equity:'650',principal:'1000',net_flows:'100',peak:'1300',existing_notional:'1250',pending_notional:'50',exchange_leverage:'25',step:'0.00000001'};
  const body=riskBody(form);
  assert.deepEqual(body,{...form,exchange_leverage:25});
  assert.equal(body.exception_approved,undefined);
  assert.equal(body.simulated_account_max,undefined);
  assert.equal(body.liquidation,undefined);
  assert.equal(form.exchange_leverage,'25');
});
test('26x is sent unchanged for the risk engine to reject, never silently lowered',()=>{
  assert.equal(riskBody({...riskDefaults,exchange_leverage:'26'}).exchange_leverage,26);
});
