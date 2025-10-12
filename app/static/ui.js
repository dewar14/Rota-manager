// Rota Builder UI Script
console.log('UI init (external JS)');

const fmt = d => d.toISOString().slice(0,10);
const tbody = document.querySelector('#peopleTbl tbody');

// Define functions globally immediately (before DOMContentLoaded)
window.addRow = function(p = {id:'', name:'', grade:'Registrar', wte:'1.0', comet:false, start_date:'', fixed_day_off:''}) {
    console.log('addRow called', p);
    const tbody = document.querySelector('#peopleTbl tbody');
    if (!tbody) {
        console.error('Table body not found');
        return;
    }
    
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><input value="${p.id}" class="pid" required style="width:85px"></td>
      <td><input value="${p.name}" class="pname" required></td>
      <td><select class="pgrade"><option ${p.grade==='Registrar'?'selected':''}>Registrar</option><option ${p.grade==='SHO'?'selected':''}>SHO</option><option ${p.grade==='Supernumerary'?'selected':''}>Supernumerary</option></select></td>
      <td><select class="pwte"><option ${p.wte==='1.0'?'selected':''}>1.0</option><option ${p.wte==='0.8'?'selected':''}>0.8</option><option ${p.wte==='0.6'?'selected':''}>0.6</option></select></td>
      <td style='text-align:center'><input type='checkbox' class='pcomet' ${p.comet?'checked':''}></td>
      <td><input type='date' class='pstart' value='${p.start_date}'></td>
      <td><input type='number' min='0' max='6' class='pfixed' value='${p.fixed_day_off}' style='width:55px'></td>
      <td><button type='button' class='delRow'>✕</button></td>`;
    tr.querySelector('.delRow').onclick = () => tr.remove();
    tbody.appendChild(tr);
}

window.loadRegistrarSet = function() {
    console.log('loadRegistrarSet called');
    const tbody = document.querySelector('#peopleTbl tbody');
    if (!tbody) {
        console.error('Table body not found');
        return;
    }
    
    const preset = [
        {name:'Mei Yi Goh', wte:'0.8', comet:true},
        {name:'David White', wte:'0.8', comet:true},
        {name:'Nikki Francis', wte:'0.8', comet:true},
        {name:'Reuben Firth', wte:'0.8', comet:true},
        {name:'Alexander Yule', wte:'0.6', comet:false},
        {name:'Abdifatah Mohamud', wte:'1.0', comet:true},
        {name:'Hanin El Abbas', wte:'0.8', comet:true},
        {name:'Sarah Hallet', wte:'0.6', comet:false},
        {name:'Manan Kamboj', wte:'1.0', comet:true},
        {name:'Mahmoud', wte:'1.0', comet:true},
        {name:'Registrar 11', wte:'1.0', comet:true}
    ];
    tbody.querySelectorAll('tr').forEach(r => r.remove());
    let idx = 1; 
    preset.forEach(p => addRow({id:'reg'+(idx++), name:p.name, grade:'Registrar', wte:p.wte, comet:p.comet}));
}

// Test functions immediately
console.log('Testing functions after definition:');
console.log('addRow exists:', typeof window.addRow);
console.log('loadRegistrarSet exists:', typeof window.loadRegistrarSet);

// Initialize when DOM loaded
document.addEventListener('DOMContentLoaded', () => {
    // Auto-load registrars and set defaults for faster testing
    loadRegistrarSet(); // Auto-preload the registrar set
    
    // Set default dates
    document.getElementById('startDate').value = '2026-02-04'; // 04/02/2026
    document.getElementById('cometFirst').value = '2026-02-09'; // 09/02/2026
    document.getElementById('enableComet').checked = true; // Enable CoMET by default
    
    // Visual confirmation
    const badge = document.createElement('span');
    badge.textContent = 'JS Loaded';
    badge.style.cssText = 'margin-left:10px;font-size:12px;color:#0a0;background:#dfd;padding:2px 6px;border-radius:10px;';
    document.querySelector('h1')?.appendChild(badge);
    
    function computeEnd(startISO, weeks) {
        const s = new Date(startISO);
        return fmt(new Date(s.getTime() + (weeks*7-1)*86400000));
    }
    
    function genComet(firstISO, endISO) {
        if(!firstISO) return [];
        let cur = new Date(firstISO);
        if(cur.getDay() !== 1) {
            cur = new Date(cur.getTime() + ((8-cur.getDay())%7)*86400000);
        }
        const end = new Date(endISO);
        const out = [];
        while(cur <= end) {
            out.push(fmt(cur));
            cur = new Date(cur.getTime() + 14*86400000);
        }
        return out;
    }
    
    document.getElementById('cfgForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        console.log('Form submission started');
        
        try {
            const start = document.getElementById('startDate').value;
            const weeks = parseInt(document.getElementById('weeks').value || '26');
            const end = computeEnd(start, weeks);
            const cometFirst = document.getElementById('cometFirst').value;
            const cometEnabled = document.getElementById('enableComet').checked;
            const cometWeeks = cometEnabled ? genComet(cometFirst || start, end) : [];
            const bank = document.getElementById('bankHolidays').value.split(/\n|,|;/).map(s => s.trim()).filter(Boolean);
            const regTrain = document.getElementById('regTrain').value.split(/\n|,|;/).map(s => s.trim()).filter(Boolean);
            const shoTrain = document.getElementById('shoTrain').value.split(/\n|,|;/).map(s => s.trim()).filter(Boolean);
            const unitTrain = document.getElementById('unitTrain').value.split(/\n|,|;/).map(s => s.trim()).filter(Boolean);
            
            const tbody = document.querySelector('#peopleTbl tbody');
            const people = Array.from(tbody.querySelectorAll('tr')).map(r => ({
                id: r.querySelector('.pid').value,
                name: r.querySelector('.pname').value,
                grade: r.querySelector('.pgrade').value,
                wte: parseFloat(r.querySelector('.pwte').value),
                comet_eligible: r.querySelector('.pcomet').checked,
                start_date: r.querySelector('.pstart').value || null,
                fixed_day_off: r.querySelector('.pfixed').value ? parseInt(r.querySelector('.pfixed').value) : null
            }));
            
            console.log('People data:', people);
            
            const problem = {
                people,
                config: {
                    start_date: start, 
                    end_date: end,
                    bank_holidays: bank, 
                    comet_on_weeks: cometWeeks,
                    registrar_training_days: regTrain, 
                    sho_training_days: shoTrain, 
                    unit_training_days: unitTrain,
                    max_day_clinicians: 5, 
                    ideal_weekday_day_clinicians: 4, 
                    min_weekday_day_clinicians: 3
                },
                weights: {
                    locum_usage: parseInt(document.getElementById('locum').value || '1000'),
                    single_night_penalty: parseInt(document.getElementById('singleNight').value || '30'),
                    fairness_variance_15pct: parseInt(document.getElementById('fairVar').value || '5'),
                    weekend_day_staffing: parseInt(document.getElementById('weekdayTarget').value || '1')
                }
            };
            
            console.log('Problem data:', problem);
            
            // Show loading message
            document.getElementById('result').innerHTML = '<h3>Solving...</h3><div id="progress"></div><p>Using staged solver with 20-minute timeout. <em>Large rotas may take several minutes...</em></p>';
            
            // Start progress polling
            const progressInterval = setInterval(async () => {
                try {
                    const progressRes = await fetch('/progress');
                    const progress = await progressRes.json();
                    
                    if (progress.active) {
                        document.getElementById('progress').innerHTML = 
                            `<p><strong>Stage:</strong> ${progress.stage}</p>
                             <p><strong>Status:</strong> ${progress.message}</p>`;
                    } else {
                        clearInterval(progressInterval);
                        if (progress.stage === 'completed') {
                            document.getElementById('progress').innerHTML = '<p style="color:green">✓ Solve completed</p>';
                        } else if (progress.stage === 'error') {
                            document.getElementById('progress').innerHTML = '<p style="color:red">✗ Error occurred</p>';
                        }
                    }
                } catch (err) {
                    console.log('Progress polling error:', err);
                }
            }, 2000);  // Poll every 2 seconds
            
            // Add timeout for long-running requests (20 minutes)  
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 1200000); // 20 minutes
            
            const res = await fetch('/solve', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({problem, staged: true}),  // Enable staged solving
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            clearInterval(progressInterval);
            
            console.log('Response status:', res.status);
            
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            }
            
            const data = await res.json();
            console.log('Solve result:', data);
            
            let html = '<h3>Result</h3>';
            if (data.success) {
                html += '<p style="color:green">✓ Solved successfully</p>';
                html += '<p><a href="/out/roster.csv" target="_blank">Download Roster CSV</a></p>';
                const locums = data.summary?.total_locum_slots || data.summary?.locum_slots || 0;
                html += `<p>Locum slots used: ${locums}</p>`;
                
                // Add visual rota table
                if (data.roster) {
                    html += generateRotaTable(data.roster, people);
                }
            } else {
                html += `<p style="color:red">✗ Failed: ${data.message || 'Unknown error'}</p>`;
            }
            document.getElementById('result').innerHTML = html;
            
        } catch (error) {
            console.error('Error during solve:', error);
            let errorMessage = error.message;
            
            if (error.name === 'AbortError') {
                errorMessage = 'Request timed out after 10 minutes. Try reducing the number of weeks or simplifying constraints.';
            } else if (errorMessage.includes('HTTP 504')) {
                errorMessage = 'Server timeout (504). The problem may be too large. Try reducing the number of weeks or people.';
            } else if (errorMessage.includes('HTTP 502') || errorMessage.includes('HTTP 503')) {
                errorMessage = 'Server temporarily unavailable. Please try again in a moment.';
            }
            
            document.getElementById('result').innerHTML = `<h3>Error</h3><p style="color:red">✗ ${errorMessage}</p><p><em>Tip: Try solving shorter periods (4-8 weeks) first to test your configuration.</em></p>`;
        }
    });
});

function generateRotaTable(roster, people) {
    // Get all dates and sort them
    const dates = Object.keys(roster).sort();
    if (dates.length === 0) return '<p>No roster data available</p>';
    
    let html = '<div class="rota-container"><h4>Generated Rota</h4>';
    html += '<table class="rota-table">';
    
    // Header row with people names
    html += '<thead><tr><th style="min-width:80px;">Date</th><th class="date-flags">Day</th>';
    people.forEach(person => {
        const shortName = person.name.split(' ').map(n => n.substring(0,1)).join('');
        html += `<th title="${person.name} (${person.grade})">${shortName}<br><span class="small">${person.grade}</span></th>`;
    });
    html += '</tr></thead><tbody>';
    
    // Data rows - one per date
    dates.forEach(dateStr => {
        const date = new Date(dateStr + 'T12:00:00'); // Avoid timezone issues
        const dayName = date.toLocaleDateString('en-GB', { weekday: 'short' });
        const dayOfWeek = date.getDay();
        const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
        
        html += `<tr ${isWeekend ? 'class="weekend-row"' : ''}>`;
        
        // Date column
        const formattedDate = date.toLocaleDateString('en-GB', { 
            day: '2-digit', 
            month: 'short' 
        });
        html += `<td class="day-cell">${formattedDate}</td>`;
        html += `<td class="day-cell small">${dayName}</td>`;
        
        // Shift columns for each person
        const dayRoster = roster[dateStr] || {};
        people.forEach(person => {
            const shift = dayRoster[person.id] || 'OFF';
            const displayShift = shift === 'OFF' ? '-' : shift;
            html += `<td class="shift-${shift}" title="${person.name}: ${shift}">${displayShift}</td>`;
        });
        
        html += '</tr>';
    });
    
    html += '</tbody></table>';
    
    // Add legend
    html += '<div style="margin-top:15px;"><h5>Legend:</h5>';
    html += '<div style="font-size:10px;display:flex;flex-wrap:wrap;gap:5px;">';
    html += '<span class="shift-LD_REG" style="padding:2px 4px;">LD</span> Long Day ';
    html += '<span class="shift-N_REG" style="padding:2px 4px;">N</span> Night ';
    html += '<span class="shift-CMD" style="padding:2px 4px;">CMD</span> CoMET Day ';
    html += '<span class="shift-CMN" style="padding:2px 4px;">CMN</span> CoMET Night ';
    html += '<span class="shift-SD" style="padding:2px 4px;">SD</span> Short Day ';
    html += '<span class="shift-CPD" style="padding:2px 4px;">CPD</span> CPD ';
    html += '<span class="shift-TREG" style="padding:2px 4px;">T</span> Training ';
    html += '<span class="shift-IND" style="padding:2px 4px;">IND</span> Induction ';
    html += '<span class="shift-LEAVE" style="padding:2px 4px;">AL</span> Leave ';
    html += '</div></div>';
    
    html += '</div>';
    return html;
}