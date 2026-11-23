import {api} from '../api.js';
import {action, badge, closeDialog, empty, errorText, esc, notice, options, picker, showDialog, table} from '../components.js';
import {allocKinds, allocStates, isManager, shifts, state} from '../state.js';

const allocTone = {held: 'amber', settled: 'green'};

function quotaDialog(regions, refresh) {
  const dialog = showDialog('设置可派人数', `<form class="form-stack">
    <div class="form-grid"><label>片区<select name="region">${options(regions.map(name => [name, name]))}</select></label>
    <label>营业日<input type="date" name="business_date" required value="${esc(state.window.end)}"></label>
    <label>班次<select name="shift">${options(Object.entries(shifts), 'afternoon')}</select></label>
    <label>可派人数<input type="number" name="capacity" min="0" max="60" value="4" required></label></div>
    <p class="muted">同片区、同营业日、同班次的支援与恢复补派共用该名额。已占用人数超过新值时保存会被拒绝。</p>
    ${errorText}<div class="form-actions"><button class="button primary" type="submit">保存名额</button></div></form>`);
  action(dialog.querySelector('form'), async fields => {
    await api.saveQuota({...fields, capacity: Number(fields.capacity)});
    closeDialog();
    notice('可派人数已保存');
    await refresh();
  });
}

function allocationCells(allocations) {
  if (!allocations.length) return '<span class="muted">暂无占用</span>';
  return allocations.map(item => `<div class="quota-alloc">${badge(allocKinds[item.kind], item.kind === 'support' ? 'neutral' : 'amber')}
    <a href="#${item.kind === 'support' ? 'supports' : 'recovery'}" data-alloc="${item.kind}:${item.order_id}">#${item.order_id}</a>
    <span>${esc(item.station_name)}</span>${badge(allocStates[item.state], allocTone[item.state])}
    <span>${item.state === 'held' ? `${item.planned} 人` : `实到 ${item.actual} 人`}</span></div>`).join('');
}

export async function quotas(node, refresh, current) {
  const [{stations}, {quotas: rows}] = await Promise.all([api.stations(), api.shiftQuotas(state.quotaRegion)]);
  if (!current()) return;
  const regions = [...new Set(stations.map(row => row.region))];
  node.innerHTML = `<div class="page-head"><div><span class="eyebrow">跨模块调度</span><h1>名额台账</h1>
    <p>同片区的支援和恢复补派共用一队人，按营业日和班次核对各单占用与还可派人数。</p></div>
    ${isManager() ? '<button class="button primary" id="set-quota" type="button">设置可派人数</button>' : ''}</div>
    <section class="paper"><header class="section-head"><div><h2>班次名额</h2>
    <p>支援获批、补派发出时占用名额；核销与核验按实到人数结算，空出的名额可再派。</p></div>${picker()}</header>
    <div class="filter-row"><label>片区<select id="quota-region">${options([['', '全部片区'], ...regions.map(name => [name, name])], state.quotaRegion)}</select></label>
    <span>共 ${rows.length} 个班次</span></div>
    ${rows.length ? table(['营业日', '片区', '班次', '可派', '在途占用', '实到结算', '还可派', '各单占用'], rows.map(row => [
      esc(row.business_date), esc(row.region), badge(shifts[row.shift], 'neutral'), `${row.capacity} 人`,
      `${row.held} 人`, `${row.settled} 人`, `<strong>${row.available} 人</strong>`, allocationCells(row.allocations),
    ])) : empty('本窗口暂无名额配置', '区域主管可点击右上角，按片区、营业日和班次设置可派人数。')}</section>`;
  action(node.querySelector('#window-form'), async data => {
    const previous = state.window;
    state.window = data;
    try { await api.shiftQuotas(state.quotaRegion); }
    catch (error) { state.window = previous; throw error; }
    await refresh();
  });
  node.querySelector('#quota-region').onchange = event => { state.quotaRegion = event.target.value; refresh(); };
  const create = node.querySelector('#set-quota');
  if (create) create.onclick = () => quotaDialog(regions, refresh);
  node.querySelectorAll('[data-alloc]').forEach(link => {
    link.onclick = () => {
      const [kind, id] = link.dataset.alloc.split(':');
      if (kind === 'support') state.supportId = Number(id);
      else state.recoveryId = Number(id);
    };
  });
}
