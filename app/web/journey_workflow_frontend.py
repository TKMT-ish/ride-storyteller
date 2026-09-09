"""Product-facing frontend for the private journey workflow.

This stays separate from app.web.server while another process is changing
that file. It calls only the existing private journey APIs and embeds no
private ride data.
"""
# ruff: noqa: E501

from __future__ import annotations

import json
from collections.abc import Sequence

from app.web.i18n import UiLanguage
from app.web.private_journey_actions import MUSIC_TRACK_IDS, NO_MUSIC_TRACK_ID

WORKFLOW_FRONTEND_SCHEMA_VERSION = "journey-workflow-frontend-v1"


def track_label(track_id: str) -> str:
    """The catalogue's ids are hyphenated titles: "enchanted-valley" is Enchanted Valley."""
    return track_id.replace("-", " ").title()


def render_journey_workflow_page(
    language: UiLanguage = UiLanguage.JAPANESE,
    *,
    track_ids: Sequence[str] = MUSIC_TRACK_IDS,
) -> str:
    """Return the dependency-free workflow page.

    `track_ids` is the music the film step will accept; the page offers exactly
    that list (the server passes its own allowlist), so a track added to the
    allowlist appears here without a second edit and nothing here can name a
    track the server would refuse.
    """

    en = language is UiLanguage.ENGLISH
    text = {
        "title": "Turn one riding day into a story" if en else "一日の旅を、一本の物語へ。",
        "intro": (
            "Your source footage stays on this Mac. Follow one clear path from intake to the finished film."
            if en
            else "元の映像はこのMacに置いたまま。素材の取り込みから完成動画まで、ひとつの流れで進めます。"
        ),
        "local": "Processed on this Mac" if en else "このMacで処理",
        "language": "日本語" if en else "English",
        "loading": "Reading this ride…" if en else "旅の状態を確認しています…",
        "empty_title": "Start with a riding day" if en else "最初の旅を取り込みましょう",
        "empty_body": (
            "No active journey was found. Add a GPX file and its footage from the configured intake folder."
            if en
            else "現在選択されている旅はありません。取り込みフォルダ内のGPXと動画フォルダを指定してください。"
        ),
        "journey": "Journey" if en else "旅",
        "switch": "Switch" if en else "切り替える",
        "progress": "Journey progress" if en else "完成までの進捗",
        "completed": "stages complete" if en else "工程が完了",
        "next": "Next step" if en else "次にすること",
        "working": "Working…" if en else "処理中…",
        "done": "The step finished." if en else "処理が完了しました。",
        "failed": "The step stopped safely." if en else "処理は安全に停止しました。",
        "retry": "Read status again" if en else "状態を再確認",
        "new": "Add another riding day" if en else "新しい旅を取り込む",
        "new_help": (
            "Use paths relative to the configured intake folder. Nothing is uploaded by this step."
            if en
            else "設定済み取り込みフォルダからの相対パスを入力します。この段階では外部送信しません。"
        ),
        "gpx": "GPX file" if en else "GPXファイル",
        "video": "Footage folder" if en else "動画フォルダ",
        "propose": "Check camera time" if en else "カメラ時刻を確認する",
        "proposal": "Suggested correction" if en else "時刻補正の提案",
        "offset": "Confirmed correction (seconds)" if en else "確定する補正値（秒）",
        "name": "Journey name" if en else "旅の名前",
        "target": "Target film length (seconds)" if en else "目標動画時間（秒）",
        "create": "Create this journey" if en else "この旅を作成する",
        "inside": "recordings overlap this ride" if en else "本の映像が旅と重なります",
        "story": "The story of this ride" if en else "この旅の物語",
        "chapter": "CHAPTER" if en else "第{n}章",
        "opening": "OPENING" if en else "オープニング",
        "clips": "clips" if en else "本",
        "story_empty": (
            "The story appears after the footage is judged."
            if en
            else "映像判定が終わると、ここに物語の構成が表示されます。"
        ),
        "privacy_local": (
            "Original GPX and 4K footage stay on this Mac."
            if en
            else "元のGPXと4K映像は、このMacから出ません。"
        ),
        "privacy_cloud": (
            "Only small, silent review copies are sent after approval."
            if en
            else "承認後、小さくした無音の判定用コピーだけを送信します。"
        ),
        "approve_first": "Before you approve" if en else "承認する前に",
        "prepare": (
            "Prepare small copies on this Mac" if en else "このMacで判定用コピーを準備する"
        ),
        "approve": (
            "Type the displayed amount to approve" if en else "表示金額を入力して費用を承認"
        ),
        "bucket": "Private analysis bucket" if en else "非公開の分析用バケット",
        "judge": "Approve and start Gemini" if en else "承認してGemini判定を開始",
        "music": "Music" if en else "音楽",
        "film": "Create the film on this Mac" if en else "このMacで動画を生成する",
        "play": "Watch the finished film" if en else "完成した動画を見る",
        "refused": "Request refused safely" if en else "操作は安全に拒否されました",
        "network": "Could not read the local service."
        if en
        else "ローカルサービスを読み込めませんでした。",
        "stages": {
            "footage_planned": "Plan footage" if en else "映像判定を計画",
            "copies_prepared": "Prepare copies" if en else "判定用コピーを準備",
            "footage_judged": "Judge footage" if en else "Geminiで映像判定",
            "inputs_checked": "Check journey" if en else "旅の入力を確認",
            "story_planned": "Shape story" if en else "旅を物語に構成",
            "film_cut": "Create film" if en else "動画を生成",
            "film_scored": "Finish soundtrack" if en else "音楽を仕上げる",
            "film_status": "Check film" if en else "動画の状態を確認",
        },
        "states": {
            "done": "Complete" if en else "完了",
            "pending": "Waiting" if en else "未実施",
            "in_progress": "In progress" if en else "進行中",
            "blocked": "Needs attention" if en else "要確認",
        },
        "actions": {
            "resolve_blocking_reasons": "Check the item that needs attention."
            if en
            else "確認が必要な項目を解消してください。",
            "prepare_the_copies": "Prepare small review copies locally. This is free and sends nothing."
            if en
            else "判定用の小さなコピーをローカルで準備します。無料で、外部送信はありません。",
            "approve_and_judge": "Review the amount and data handling, then approve Gemini judgement."
            if en
            else "費用とデータの扱いを確認し、Gemini判定を承認します。",
            "wait_for_the_judgement": "Gemini judgement is running. This page updates automatically."
            if en
            else "Geminiが判定中です。この画面は自動で更新されます。",
            "make_the_film": "Build the story film locally from confirmed evidence."
            if en
            else "確認済みの証拠から、このMacで物語動画を生成します。",
            "choose_music": "Choose music, then render the final version."
            if en
            else "音楽を選び、最終版を生成します。",
            "watch_the_film": "Your journey film is ready." if en else "旅の動画が完成しました。",
        },
        "tracks": {
            NO_MUSIC_TRACK_ID: "No music" if en else "音楽なし",
            **{track_id: track_label(track_id) for track_id in track_ids},
        },
    }
    values = {
        "__LANG__": language.value,
        "__OTHER__": "ja" if en else "en",
        "__LANGUAGE__": str(text["language"]),
        "__TITLE__": str(text["title"]),
        "__INTRO__": str(text["intro"]),
        "__LOCAL__": str(text["local"]),
        "__LOADING__": str(text["loading"]),
        "__TEXT__": json.dumps(text, ensure_ascii=False).replace("<", "\\u003c"),
        "__SCHEMA__": WORKFLOW_FRONTEND_SCHEMA_VERSION,
    }
    page = _PAGE
    for marker, value in values.items():
        page = page.replace(marker, value)
    return page


_PAGE = """<!doctype html>
<html lang="__LANG__"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><meta name="ride-storyteller-ui" content="__SCHEMA__">
<title>Ride Storyteller</title>
<style>
:root{--ink:#f5f2ea;--muted:#a9b1af;--bg:#0b1112;--panel:#111a1b;--line:#293637;--green:#93d0b0;--amber:#efb866;--red:#ef806d;--shadow:0 18px 50px rgba(0,0,0,.28)}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(circle at 78% 0%,rgba(44,100,86,.22),transparent 32rem),var(--bg);font-family:Inter,"Hiragino Sans","Noto Sans JP",system-ui,sans-serif;line-height:1.55}button,input,select{font:inherit}button{cursor:pointer}button:disabled{cursor:wait;opacity:.58}
.shell{min-height:100vh;display:grid;grid-template-columns:17rem minmax(0,1fr)}.rail{position:sticky;top:0;height:100vh;padding:1.5rem 1.25rem;border-right:1px solid var(--line);background:rgba(8,14,15,.9)}.rail-in{height:100%;display:flex;flex-direction:column}.brand{display:flex;gap:.75rem;align-items:center;margin-bottom:2rem}.mark{width:2.5rem;height:2.5rem;border:1px solid #42645a;border-radius:50%;display:grid;place-items:center;background:#13221f}.mark svg{width:1.45rem}.brand strong{font-size:1rem}.eyebrow{margin:0;color:var(--green);font-size:.66rem;font-weight:750;letter-spacing:.14em}.rail-note{margin-top:auto;color:var(--muted);font-size:.77rem;border-top:1px solid var(--line);padding-top:1rem}
.mini{display:grid;gap:.28rem;list-style:none;padding:0;margin:0}.mini li{display:grid;grid-template-columns:1.4rem 1fr;gap:.55rem;align-items:center;padding:.48rem .55rem;border-radius:.5rem;color:#87918f;font-size:.8rem}.mini .active{background:#182524;color:var(--ink)}.dot{width:.55rem;height:.55rem;border-radius:50%;background:#344241;margin:auto}.active .dot{background:var(--amber);box-shadow:0 0 0 4px rgba(239,184,102,.12)}
.main{padding:2rem clamp(1.25rem,4vw,4rem) 5rem;max-width:96rem;width:100%;margin:auto}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:2.5rem}.pill{display:inline-flex;align-items:center;gap:.45rem;color:var(--green);background:rgba(147,208,176,.08);border:1px solid rgba(147,208,176,.25);border-radius:999px;padding:.42rem .72rem;font-size:.75rem;font-weight:700}.pill:before{content:"";width:.45rem;height:.45rem;border-radius:50%;background:var(--green)}.language{color:var(--muted);font-size:.8rem}
.hero{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(16rem,.65fr);gap:3rem;align-items:end;margin-bottom:2.4rem}h1{font-family:Georgia,"Yu Mincho",serif;font-size:clamp(2.2rem,5vw,5rem);line-height:1.02;letter-spacing:-.035em;margin:.35rem 0 1rem;max-width:13ch;font-weight:500}.lede{max-width:43rem;color:var(--muted);font-size:1.05rem;margin:0}.route{min-height:8.5rem;position:relative}.route svg{width:100%;height:100%;position:absolute}.route path{fill:none;stroke:#4f756a;stroke-width:2;stroke-dasharray:5 8}.route circle{fill:var(--amber)}
.notice{min-height:1.6rem;margin:.5rem 0 1.1rem;color:var(--muted);font-size:.85rem}.notice.error{color:var(--red)}.notice.success{color:var(--green)}.workspace{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(18rem,.6fr);gap:1rem;align-items:start}.card{background:linear-gradient(145deg,rgba(22,33,34,.98),rgba(14,22,23,.98));border:1px solid var(--line);border-radius:1rem;box-shadow:var(--shadow)}.pad{padding:1.25rem}.card h2{font-size:.76rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:0 0 1rem}
select,input{color:var(--ink);background:#0c1415;border:1px solid #334342;border-radius:.5rem;padding:.62rem .7rem;min-height:2.65rem;max-width:100%}select:focus,input:focus,button:focus-visible,a:focus-visible{outline:2px solid var(--amber);outline-offset:2px}.switch{display:flex;gap:.55rem;align-items:center;margin-bottom:1.25rem}.switch select{min-width:12rem}.head{display:flex;justify-content:space-between;align-items:end}.number{font:500 2rem/1 Georgia,serif}.small{color:var(--muted);font-size:.78rem}.bar{height:.35rem;background:#263334;border-radius:999px;overflow:hidden;margin:.7rem 0 1.25rem}.bar span{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--amber))}
.stages{list-style:none;padding:0;margin:0}.stage{display:grid;grid-template-columns:2rem 1fr auto;gap:.8rem;align-items:center;padding:.78rem .2rem;border-top:1px solid rgba(67,82,82,.45)}.stage:first-child{border-top:0}.stage-no{width:1.7rem;height:1.7rem;border-radius:50%;display:grid;place-items:center;background:#202d2e;color:#9da6a4;font-size:.72rem;font-weight:700}.done .stage-no{background:var(--green);color:#0a1712}.in_progress .stage-no{background:var(--amber);color:#1d150a}.stage-name{font-weight:650;font-size:.9rem}.facts{color:var(--muted);font-size:.72rem}.state{font-size:.68rem;font-weight:750;text-transform:uppercase;color:var(--muted)}.done .state{color:var(--green)}.in_progress .state{color:var(--amber)}.blocked .state{color:var(--red)}
.action{border-color:#405952;background:linear-gradient(145deg,#192b27,#121b1c)}.next-copy{font-family:Georgia,"Yu Mincho",serif;font-size:1.4rem;line-height:1.3}.controls{display:grid;gap:.75rem;margin-top:1.1rem}.field{display:grid;gap:.3rem}.field span{font-size:.72rem;color:var(--muted)}.fields{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}.button{display:inline-block;border:0;border-radius:.55rem;background:var(--ink);color:#111918;padding:.72rem 1rem;font-weight:800;min-height:2.75rem;text-decoration:none}.button.primary{background:var(--amber);color:#201609}.button.danger{background:var(--red);color:#21100d}.button.ghost{background:transparent;color:var(--ink);border:1px solid #465756}.disclosure{padding:.85rem;border:1px solid #43544f;border-radius:.65rem;background:#101b19;font-size:.75rem}.disclosure strong{color:var(--green)}
.story{margin-top:1rem}.chapters{display:grid;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:.7rem}.chapter{padding:1rem;border:1px solid var(--line);border-radius:.72rem;background:#101718}.chapter b{color:var(--amber);font-size:.65rem}.chapter h3{font:500 1.05rem Georgia,"Yu Mincho",serif;margin:.35rem 0}.film{width:100%;max-height:33rem;background:#050707;border-radius:.7rem}
details{margin-top:1rem}summary{padding:1.1rem 1.25rem;cursor:pointer;font-weight:750}summary:after{content:"＋";float:right;color:var(--amber)}details[open] summary:after{content:"−"}.intake{border-top:1px solid var(--line);padding:1.25rem}.proposal{margin-top:1rem;padding:1rem;border:1px solid #334342;border-radius:.7rem}.empty{padding:2rem}.empty h2{font:500 1.7rem Georgia,"Yu Mincho",serif;color:var(--ink);text-transform:none}.skeleton{height:24rem;background:#172323;border-radius:1rem;animation:pulse 1.2s infinite alternate}@keyframes pulse{to{opacity:.55}}
@media(max-width:880px){.shell{grid-template-columns:1fr}.rail{display:none}.hero{grid-template-columns:1fr}.route{display:none}.workspace{grid-template-columns:1fr}}@media(max-width:560px){.main{padding:1.2rem}.fields{grid-template-columns:1fr}.stage{grid-template-columns:1.8rem 1fr}.state{grid-column:2}.switch{align-items:stretch;flex-direction:column}}@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head>
<body><div class="shell">
<aside class="rail"><div class="rail-in"><div class="brand"><div class="mark"><svg viewBox="0 0 32 32"><path d="M4 24c5-1 5-8 10-9 4-1 4 5 8 4 3-1 3-6 6-9" fill="none" stroke="#efb866" stroke-width="2.4"/><circle cx="4" cy="24" r="2"/><circle cx="28" cy="10" r="2"/></svg></div><div><strong>Ride Storyteller</strong><p class="eyebrow">PRIVATE JOURNEY</p></div></div><ol class="mini" id="mini"></ol><div class="rail-note" id="rail-note"></div></div></aside>
<main class="main"><div class="top"><span class="pill">__LOCAL__</span><a class="language" href="/workflow?lang=__OTHER__">__LANGUAGE__</a></div>
<section class="hero"><div><p class="eyebrow">PRIVATE JOURNEY WORKSPACE</p><h1>__TITLE__</h1><p class="lede">__INTRO__</p></div><div class="route"><svg viewBox="0 0 320 130" preserveAspectRatio="none"><path d="M8 105 C42 118 54 48 97 68 S153 112 177 62 S241 20 311 31"/><circle cx="8" cy="105" r="5"/><circle cx="311" cy="31" r="5"/></svg></div></section>
<p class="notice" id="notice" role="status" aria-live="polite"></p><div id="app"><div class="skeleton" aria-label="__LOADING__"></div></div></main>
</div>
<script>
const T=__TEXT__,API="/api/private-journey";let timer=null;
const esc=(v)=>String(v??"").replace(/[&<>"']/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function tell(m,c=""){let e=document.getElementById("notice");e.textContent=m||"";e.className="notice "+c}
async function get(path,options={}){let r=await fetch(path,{cache:"no-store",...options}),p={};try{p=await r.json()}catch(_e){}if(!r.ok){let e=new Error(p.error||T.network);e.status=r.status;throw e}return p}
function facts(s){let a=[];if(s.key==="footage_planned"&&s.state==="done")a.push(s.watched_count+" clips",s.upload_megabytes+" MB","¥"+s.cost_jpy);if(s.wanted_count!==undefined)a.push((s.prepared_count??s.judged_count??0)+" / "+s.wanted_count);if(s.beat_count!==undefined)a.push(s.beat_count+" beats");if(s.megabytes!==undefined)a.push(s.megabytes+" MB");if(s.blocking_reasons?.length)a.push(s.blocking_reasons.join(" · "));return a.map(esc).join(" · ")}
function rows(stages){return stages.map((s,i)=>'<li class="stage '+esc(s.state)+'"><span class="stage-no">'+(s.state==="done"?"✓":i+1)+'</span><div><div class="stage-name">'+esc(T.stages[s.key]||s.key)+'</div><div class="facts">'+facts(s)+'</div></div><span class="state">'+esc(T.states[s.state]||s.state)+"</span></li>").join("")}
function miniature(stages){document.getElementById("mini").innerHTML=stages.map((s)=>'<li class="'+(s.state==="in_progress"?"active":"")+'"><span class="dot"></span>'+esc(T.stages[s.key]||s.key)+"</li>").join("")}
function disclosure(d){if(!d)return '<div class="disclosure"><strong>'+esc(T.approve_first)+'</strong><br>'+esc(T.privacy_local)+" "+esc(T.privacy_cloud)+"</div>";let w=d.sent_per_window||{},r=d.retention||{};return '<div class="disclosure"><strong>'+esc(T.approve_first)+'</strong><br>'+esc(w.seconds)+"s · "+esc(w.height_px)+"p · "+esc(w.fps)+"fps · "+esc((d.recipients||[]).join(", "))+" · "+esc(r.default_days)+" days</div>"}
function controls(p){let n=p.next_action,plan=p.stages.find((s)=>s.key==="footage_planned");if(p.job?.state==="running")return '<p class="small">'+esc(T.working)+" "+esc(p.job.elapsed_s)+"s</p>";if(n==="prepare_the_copies")return '<button class="button primary" data-action="preflight">'+esc(T.prepare)+"</button>";if(n==="approve_and_judge"&&plan)return disclosure(p.data_handling)+'<label class="field"><span>'+esc(T.approve)+" · ¥"+esc(plan.cost_jpy)+'</span><input id="approve" inputmode="decimal" placeholder="'+esc(plan.cost_jpy)+'"></label><label class="field"><span>'+esc(T.bucket)+'</span><input id="bucket" autocomplete="off"></label><button class="button danger" data-action="judge">'+esc(T.judge)+"</button>";if(n==="make_the_film"||n==="choose_music")return '<label class="field"><span>'+esc(T.music)+'</span><select id="music">'+Object.entries(T.tracks).map(([v,l])=>'<option value="'+esc(v)+'">'+esc(l)+"</option>").join("")+'</select></label><button class="button primary" data-action="film">'+esc(T.film)+"</button>";if(n==="watch_the_film")return '<a class="button primary" href="#story">'+esc(T.play)+"</a>";return '<button class="button ghost" data-action="reload">'+esc(T.retry)+"</button>"}
function intake(open=false){return '<details class="card" '+(open?"open":"")+"><summary>"+esc(T.new)+'</summary><div class="intake"><p class="small">'+esc(T.new_help)+'</p><div class="fields"><label class="field"><span>'+esc(T.gpx)+'</span><input id="in-gpx"></label><label class="field"><span>'+esc(T.video)+'</span><input id="in-video"></label></div><div class="controls"><button class="button ghost" data-action="propose">'+esc(T.propose)+'</button></div><div id="proposal"></div></div></details>'}
function proposal(p){let b=p.proposed;document.getElementById("proposal").innerHTML='<div class="proposal"><strong>'+esc(T.proposal)+": "+esc(b.offset_hours)+"h ("+esc(b.offset_s)+'s)</strong><p class="small">'+esc(b.recordings_inside)+" / "+esc(b.recordings_total)+" "+esc(T.inside)+'</p><div class="fields"><label class="field"><span>'+esc(T.offset)+'</span><input id="in-offset" value="'+esc(b.offset_s)+'"></label><label class="field"><span>'+esc(T.name)+'</span><input id="in-name"></label><label class="field"><span>'+esc(T.target)+'</span><input id="in-target" value="300"></label></div><div class="controls"><button class="button primary" data-action="create">'+esc(T.create)+"</button></div></div>";wire()}
function render(p){clearTimeout(timer);let s=p.stages||[],done=s.filter((x)=>x.state==="done").length,percent=s.length?Math.round(done/s.length*100):0,packages=p.packages||[];miniature(s);let picker=packages.length?'<div class="switch"><label>'+esc(T.journey)+'</label><select id="package">'+packages.map((n)=>'<option value="'+esc(n)+'" '+(n===p.package?"selected":"")+">"+esc(n)+"</option>").join("")+'</select><button class="button ghost" data-action="select">'+esc(T.switch)+"</button></div>":"";document.getElementById("app").innerHTML='<div class="workspace"><section class="card pad">'+picker+'<div class="head"><div><h2>'+esc(T.progress)+'</h2><span class="small">'+done+" / "+s.length+" "+esc(T.completed)+'</span></div><span class="number">'+percent+'%</span></div><div class="bar"><span style="width:'+percent+'%"></span></div><ol class="stages">'+rows(s)+'</ol></section><aside class="card pad action"><h2>'+esc(T.next)+'</h2><p class="next-copy">'+esc(T.actions[p.next_action]||T.states.blocked)+'</p><div class="controls">'+controls(p)+'</div><p class="small">'+esc(T.privacy_local)+'</p></aside></div><section class="card pad story" id="story"><h2>'+esc(T.story)+'</h2><p class="small">'+esc(T.story_empty)+"</p></section>"+intake();wire();story();if(p.job?.state==="running"||s.some((x)=>x.state==="in_progress"))timer=setTimeout(load,5000)}
function empty(){miniature([]);document.getElementById("app").innerHTML='<section class="card empty"><h2>'+esc(T.empty_title)+'</h2><p>'+esc(T.empty_body)+"</p></section>"+intake(true);wire()}
async function story(){let h=document.getElementById("story");if(!h)return;try{let p=await get(API+"/story"),html="<h2>"+esc(T.story)+"</h2>";if(p.film?.available)html+='<video class="film" controls preload="metadata" src="/private-journey/film"></video>';let n=0;html+='<div class="chapters">'+(p.chapters||[]).map((c)=>{let titled=Boolean(c.title),label=titled?(T.chapter.includes("{n}")?T.chapter.replace("{n}",String(++n)):T.chapter+" "+(++n)):T.opening,facts=[c.body,(c.windows||[]).length+" "+T.clips].filter(Boolean);return '<article class="chapter"><b>'+esc(label)+"</b>"+(titled?"<h3>"+esc(c.title)+"</h3>":"")+'<p class="small">'+facts.map(esc).join(" · ")+"</p></article>"}).join("")+"</div>";h.innerHTML=html}catch(_e){}}
async function act(a,b){let body={},path=API+"/"+a;if(a==="judge"){body.approve_jpy=document.getElementById("approve")?.value||"";body.bucket=document.getElementById("bucket")?.value||""}if(a==="film")body.music=document.getElementById("music")?.value||"none";if(a==="select")body.name=document.getElementById("package")?.value||"";if(a==="propose"||a==="create"){body.gpx=document.getElementById("in-gpx")?.value||"";body.video_root=document.getElementById("in-video")?.value||"";path=API+"/intake/"+a}if(a==="create"){body.offset_s=document.getElementById("in-offset")?.value||"";body.name=document.getElementById("in-name")?.value||"";body.target_duration_s=document.getElementById("in-target")?.value||"300"}b.disabled=true;try{let r=await get(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});if(a==="propose"){proposal(r);tell("");return}tell(T.done,"success");await load()}catch(e){tell(T.refused+": "+e.message,"error");b.disabled=false}}
function wire(){document.querySelectorAll("[data-action]").forEach((b)=>{if(b.dataset.wired)return;b.dataset.wired="1";b.onclick=()=>b.dataset.action==="reload"?load():act(b.dataset.action,b)})}
async function load(){try{let p=await get(API);tell(p.job?.state==="failed"?T.failed:"",p.job?.state==="failed"?"error":"");render(p)}catch(e){tell(e.status===503?"":T.network,e.status===503?"":"error");empty()}}
document.getElementById("rail-note").textContent=T.privacy_local+" "+T.privacy_cloud;load();
</script></body></html>"""
