
const document = {};
const allInputs = [];
const rows = [];
const mkInput = (name, value, visible, row) => ({
  attr: {name, id: name}, value, visible, row,
  getAttribute(a){ return this.attr[a]; },
  get offsetWidth(){ return this.visible ? 100 : 0; },
  getClientRects(){ return this.visible ? [{x:0,y:0,width:100,height:20}] : []; },
  closest(sel){ return sel === 'tr' ? this.row : null; },
});
const mkRow = () => ({ innerText: '', inputs: [], querySelectorAll(sel){ return sel.startsWith('input') ? this.inputs : []; } });
const rHel2 = mkRow(); rows.push(rHel2);
const nHel2 = mkInput('_NOTA_0008', '0,0', true, rHel2);
const nomeHel2 = mkInput('_ALUMATNOM_0008', 'HELOISA RAMALHO MOHR', true, rHel2);
rHel2.inputs.push(nHel2, nomeHel2);
allInputs.push(nHel2, nomeHel2);
document.querySelectorAll = (sel) => sel.startsWith('input') ? allInputs : rows;


const A = ({suffix, coluna, alvo}) => {

    const _sim = (a, b) => {
        a = (a || '').toLowerCase(); b = (b || '').toLowerCase();
        if (a === b) return 1;
        if (!a || !b) return 0;
        const n = a.length, m = b.length;
        const dp = Array.from({length: n + 1}, () => new Array(m + 1).fill(0));
        for (let i = 0; i <= n; i++) dp[i][0] = i;
        for (let j = 0; j <= m; j++) dp[0][j] = j;
        for (let i = 1; i <= n; i++) {
            for (let j = 1; j <= m; j++) {
                dp[i][j] = Math.min(dp[i-1][j] + 1, dp[i][j-1] + 1, dp[i-1][j-1] + (a[i-1] === b[j-1] ? 0 : 1));
            }
        }
        return 1 - dp[n][m] / Math.max(n, m);
    };
    const _norm = s => (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    const _tokenize = s => Array.from(new Set((_norm(s).match(/[a-z0-9]{2,}/g) || [])));
    const _gradeFieldRe = new RegExp('_(?!(?:notarec|notrec|recup|recuperacao|recupera|alumnom|alumatnom|aluno|nome|estudante|estu|matricula|matric|mat))[a-z0-9]{1,24}_0008$');
    const _isGradeField = (name, id) => _gradeFieldRe.test(_norm(name)) || _gradeFieldRe.test(_norm(id));
    const _vis = el => { try { return !!el && (el.offsetWidth > 0 || el.getClientRects().length > 0); } catch (e) { return true; } };
    const _rowTokens = (row) => {
        const parts = [row.innerText || ''];
        try {
            row.querySelectorAll('input[type="text"], input[type="number"], input[type="hidden"]').forEach(x => {
                const v = (x.value || '').trim();
                if (/[a-z\u00c0-\u00ff]/i.test(v)) parts.push(v);
            });
        } catch (e) {}
        return _tokenize(parts.join(' '));
    };
    
    const alvoTokens = alvo ? _tokenize(alvo) : [];
    console.log('alvoTokens', JSON.stringify(alvoTokens));
    const candidates = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'));
    const hits = [];
    for (const el of candidates) {
        if (!_isGradeField(el.getAttribute('name'), el.getAttribute('id'))) continue;
        if (!_vis(el)) continue;
        const row = el.closest('tr');
        const rowTokens = _rowTokens(row);
        console.log('cand', el.getAttribute('name'), 'rowTokens', JSON.stringify(rowTokens));
        if (!rowTokens.length) continue;
        let hit = 0;
        for (const t of alvoTokens) { if (rowTokens.some(rt => _sim(t, rt) >= 0.8)) hit += 1; }
        console.log('hit', hit, 'need', Math.max(1, Math.ceil(alvoTokens.length * 0.6)));
        if (hit < Math.max(1, Math.ceil(alvoTokens.length * 0.6))) continue;
        const rowInputs = Array.from(row.querySelectorAll('input[type="text"], input[type="number"]')).filter(i => {
            return _isGradeField(i.getAttribute('name'), i.getAttribute('id')) && _vis(i);
        });
        hits.push({value: el.value.trim(), count: rowInputs.length, matched: hit});
    }
    if (!hits.length) return null;
    hits.sort((a, b) => b.matched - a.matched || a.count - b.count);
    return {value: hits[0].value, count: hits[0].count};
}


console.log('RESULT:', JSON.stringify(A({suffix:'0008', coluna:'', alvo:'Heloisa Sitoria'})));
