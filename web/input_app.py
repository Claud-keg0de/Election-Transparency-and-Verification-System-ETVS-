"""ETVS local form-driven source-entry application.

Normal human data entry happens here; seed.py remains a deterministic test
fixture tool rather than the source-entry interface.
"""
from __future__ import annotations
import os
import secrets
from datetime import datetime, timezone
import blake3
import psycopg
from flask import Flask, render_template_string, request
from psycopg.rows import dict_row

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("ETVS_FLASK_SECRET") or secrets.token_hex(32)
app.jinja_env.autoescape = True
POSITIONS=("POS-PRESIDENT","POS-GOVERNOR","POS-SENATOR","POS-WOMEN-REP","POS-MP","POS-MCA")

SHELL="""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETVS Source Input</title><style>
body{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;line-height:1.45}
nav{display:flex;gap:.7rem;flex-wrap:wrap;margin-bottom:1.5rem}nav a{padding:.5rem .75rem;border:1px solid #ccc;border-radius:6px;text-decoration:none}
section{border:1px solid #ddd;border-radius:10px;padding:1rem;margin:1rem 0}label{display:block;font-weight:600;margin:.7rem 0 .25rem}
input,select{width:100%;box-sizing:border-box;padding:.6rem;border:1px solid #aaa;border-radius:5px}button{margin-top:1rem;padding:.65rem 1rem;border:0;border-radius:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem}.notice{padding:.8rem;border-radius:6px;background:#f3f3f3}
.error{background:#ffe9e9;border:1px solid #cc7777}.ok{background:#e9f7e9;border:1px solid #77aa77}
table{width:100%;border-collapse:collapse}th,td{padding:.5rem;border-bottom:1px solid #ddd;text-align:left}.small{font-size:.9rem;color:#555}
</style></head><body><h1>ETVS Source Input</h1><nav>
<a href="/">Dashboard</a><a href="/polling-stations/new">Polling Station</a><a href="/turnout">Turnout / Votes Cast</a><a href="/contest">Results + Ballot Accounting</a>
</nav>{% if message %}<div class="notice {{'error' if error else 'ok'}}">{{message}}</div>{% endif %}{{body|safe}}</body></html>"""

def db():
    return psycopg.connect(host=os.getenv("ETVS_DB_HOST","localhost"),port=int(os.getenv("ETVS_DB_PORT","5432")),
                           dbname=os.getenv("ETVS_DB_NAME","etvs"),user=os.getenv("ETVS_DB_USER","postgres"),
                           password=os.getenv("ETVS_DB_PASSWORD",""),row_factory=dict_row)
def now(): return datetime.now(timezone.utc)
def hash_input(*parts): return blake3.blake3("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()
def nonneg(name,value):
    if value is None or value.strip()=="": raise ValueError(f"{name} is required.")
    n=int(value)
    if n<0: raise ValueError(f"{name} cannot be negative.")
    return n
def render(body,message=None,error=False): return render_template_string(SHELL,body=body,message=message,error=error)

@app.get("/")
def index():
    with db() as c, c.cursor() as q:
        stations=q.execute("""SELECT ps.polling_station_id,ps.polling_station_code,ps.registered_voters,e.election_name,
                                     w.ward_name,co.county_name,c.constituency_name
                                FROM polling_stations ps JOIN elections e ON e.election_id=ps.election_id
                                JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id
                                JOIN wards w ON w.ward_id=rc.ward_id JOIN constituencies c ON c.constituency_id=w.constituency_id
                                JOIN counties co ON co.county_id=c.county_id
                               ORDER BY co.county_name,c.constituency_name,w.ward_name,ps.polling_station_code""").fetchall()
    body=render_template_string("""<p class="notice"><strong>Human source entry is form-driven.</strong> seed.py is not required for normal data entry.</p>
    <section><h2>Polling stations</h2><table><tr><th>Station</th><th>Election</th><th>County</th><th>Constituency</th><th>Ward</th><th>Registered</th></tr>
    {% for s in stations %}<tr><td>{{s.polling_station_code}} ({{s.polling_station_id}})</td><td>{{s.election_name}}</td><td>{{s.county_name}}</td><td>{{s.constituency_name}}</td><td>{{s.ward_name}}</td><td>{{s.registered_voters}}</td></tr>{% endfor %}</table></section>""",stations=stations)
    return render(body)

@app.route("/polling-stations/new",methods=["GET","POST"])
def new_station():
    message=None; error=False
    with db() as c,c.cursor() as q:
        elections=q.execute("SELECT election_id,election_name FROM elections ORDER BY election_date DESC").fetchall()
        wards=q.execute("""SELECT w.ward_id,w.ward_name,c.constituency_name,co.county_name FROM wards w
                           JOIN constituencies c ON c.constituency_id=w.constituency_id JOIN counties co ON co.county_id=c.county_id
                           ORDER BY co.county_name,c.constituency_name,w.ward_name""").fetchall()
        if request.method=="POST":
            try:
                eid=request.form["election_id"]; wid=request.form["ward_id"]; sid=request.form["polling_station_id"].strip()
                code=request.form["polling_station_code"].strip(); centre=request.form["registration_centre_name"].strip()
                reg=nonneg("Registered voters",request.form.get("registered_voters"))
                interval=nonneg("Turnout interval",request.form.get("turnout_interval_minutes"))
                if not sid or not code or not centre: raise ValueError("Station ID, station code and registration-centre name are required.")
                if not 1<=interval<=1440: raise ValueError("Turnout interval must be 1-1440 minutes.")
                rcid="RC-"+sid
                q.execute("""INSERT INTO registration_centres(registration_centre_id,registration_centre_name,ward_id)
                             VALUES(%s,%s,%s) ON CONFLICT(registration_centre_id) DO UPDATE
                             SET registration_centre_name=EXCLUDED.registration_centre_name,ward_id=EXCLUDED.ward_id""",(rcid,centre,wid))
                q.execute("""INSERT INTO polling_stations(polling_station_id,election_id,registration_centre_id,polling_station_code,
                             registered_voters,turnout_reporting_interval_minutes) VALUES(%s,%s,%s,%s,%s,%s)""",
                          (sid,eid,rcid,code,reg,interval))
                c.commit(); message=f"Polling station {sid} saved."
            except Exception as exc: c.rollback(); error=True; message=str(exc)
    body=render_template_string("""<section><h2>Polling station details</h2><p class="small">County, constituency and ward are read-only reference geography.</p>
    <form method="post"><div class="grid"><div><label>Election</label><select name="election_id">{% for e in elections %}<option value="{{e.election_id}}">{{e.election_name}} — {{e.election_id}}</option>{% endfor %}</select></div>
    <div><label>Ward</label><select name="ward_id">{% for w in wards %}<option value="{{w.ward_id}}">{{w.county_name}} / {{w.constituency_name}} / {{w.ward_name}} — {{w.ward_id}}</option>{% endfor %}</select></div>
    <div><label>Polling station ID</label><input name="polling_station_id" required></div><div><label>Polling station code</label><input name="polling_station_code" required></div>
    <div><label>Registration centre name</label><input name="registration_centre_name" required></div><div><label>Registered voters</label><input name="registered_voters" type="number" min="0" required></div>
    <div><label>Turnout reporting interval (minutes)</label><input name="turnout_interval_minutes" type="number" min="1" max="1440" value="30" required></div></div>
    <button type="submit">Save polling station</button></form></section>""",elections=elections,wards=wards)
    return render(body,message,error)

@app.route("/turnout",methods=["GET","POST"])
def turnout():
    message=None; error=False
    with db() as c,c.cursor() as q:
        stations=q.execute("SELECT polling_station_id,polling_station_code,election_id,registered_voters FROM polling_stations ORDER BY polling_station_code").fetchall()
        if request.method=="POST":
            try:
                sid=request.form["polling_station_id"]; value=nonneg("Turnout",request.form.get("voters_turnout"))
                st=q.execute("SELECT * FROM polling_stations WHERE polling_station_id=%s",(sid,)).fetchone()
                if not st: raise ValueError("Polling station does not exist.")
                if value>st["registered_voters"]: raise ValueError("Turnout/votes cast cannot exceed registered voters.")
                previous=q.execute("SELECT observed_at FROM turnout_observations WHERE election_id=%s AND polling_station_id=%s ORDER BY observation_version DESC LIMIT 1",
                                   (st["election_id"],sid)).fetchone()
                t=now()
                if previous is not None:
                    elapsed=(t-previous["observed_at"]).total_seconds()/60
                    if elapsed < st["turnout_reporting_interval_minutes"]:
                        raise ValueError(f"Next turnout observation is not due yet. The station interval is {st['turnout_reporting_interval_minutes']} minutes; only {elapsed:.1f} minutes have elapsed.")
                v=q.execute("SELECT COALESCE(MAX(observation_version),0)+1 AS v FROM turnout_observations WHERE election_id=%s AND polling_station_id=%s",
                            (st["election_id"],sid)).fetchone()["v"]
                h=hash_input("TURNOUT",st["election_id"],sid,v,value,t.isoformat())
                q.execute("""INSERT INTO turnout_observations(election_id,polling_station_id,observation_version,voters_turnout,observed_at,input_hash)
                             VALUES(%s,%s,%s,%s,%s,%s)""",(st["election_id"],sid,v,value,t,h))
                c.commit(); message=f"Turnout {value} saved for {sid}."
            except Exception as exc: c.rollback(); error=True; message=str(exc)
    body=render_template_string("""<section><h2>Turnout / votes cast</h2><p class="small">Turnout is a variable observed input recorded at the station's configured interval; ETVS never derives it from registered voters.</p>
    <form method="post"><label>Polling station</label><select name="polling_station_id">{% for s in stations %}<option value="{{s.polling_station_id}}">{{s.polling_station_code}} — registered {{s.registered_voters}}</option>{% endfor %}</select>
    <label>Voters who cast a ballot (turnout)</label><input name="voters_turnout" type="number" min="0" required><button type="submit">Save turnout</button></form></section>""",stations=stations)
    return render(body,message,error)

@app.get("/health/db")
def health_db():
    try:
        with db() as c, c.cursor() as q:
            q.execute("SELECT current_database(), current_user")
            row = q.fetchone()
            database, user = row["current_database"], row["current_user"]
            q.execute("SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema='public'")
            tables = q.fetchone()["n"]
        return {"status":"connected","database":database,"user":user,"public_tables":tables}, 200
    except Exception as exc:
        return {"status":"error","message":str(exc)}, 503

@app.route("/contest",methods=["GET","POST"])
def contest():
    message=None; error=False
    with db() as c,c.cursor() as q:
        stations=q.execute("SELECT polling_station_id,polling_station_code,election_id,registered_voters FROM polling_stations ORDER BY polling_station_code").fetchall()
        positions=q.execute("""SELECT position_id,position_name FROM positions WHERE position_id=ANY(%s)
                               ORDER BY position_name""",(list(POSITIONS),)).fetchall()
        sid=request.values.get("polling_station_id"); pid=request.values.get("position_id")
        candidates=[]; turnout_value=None
        if sid:
            st=q.execute("SELECT election_id FROM polling_stations WHERE polling_station_id=%s",(sid,)).fetchone()
            if st:
                t=q.execute("""SELECT voters_turnout FROM turnout_observations WHERE election_id=%s AND polling_station_id=%s
                               ORDER BY observation_version DESC LIMIT 1""",(st["election_id"],sid)).fetchone()
                turnout_value=t["voters_turnout"] if t else None
                if pid:
                    candidates=q.execute("""SELECT candidate_id,candidate_name FROM candidates WHERE election_id=%s AND position_id=%s
                                            ORDER BY candidate_name""",(st["election_id"],pid)).fetchall()
        if request.method=="POST":
            try:
                if turnout_value is None: raise ValueError("Enter station turnout before contest accounting.")
                if not pid: raise ValueError("Select a contest.")
                rejected=nonneg("Rejected ballots",request.form.get("rejected_votes"))
                spoilt=nonneg("Spoilt ballots",request.form.get("spoilt_ballots"))
                votes={x["candidate_id"]:nonneg(x["candidate_name"],request.form.get("vote_"+x["candidate_id"])) for x in candidates}
                valid=sum(votes.values())
                if valid+rejected != turnout_value:
                    raise ValueError(f"Turnout {turnout_value} must equal valid votes {valid} + rejected ballots {rejected}. Spoilt ballots are excluded because they were not cast.")
                eid=q.execute("SELECT election_id FROM polling_stations WHERE polling_station_id=%s",(sid,)).fetchone()["election_id"]; t=now()
                for cid,vote in votes.items():
                    rv=q.execute("""SELECT COALESCE(MAX(result_version),0)+1 AS v FROM result_submissions
                                    WHERE election_id=%s AND polling_station_id=%s AND candidate_id=%s""",(eid,sid,cid)).fetchone()["v"]
                    rh=hash_input("RESULT",eid,sid,cid,pid,rv,vote,t.isoformat())
                    q.execute("""INSERT INTO result_submissions(election_id,polling_station_id,candidate_id,result_version,votes,position_id,
                                 submission_hash,submitted_at,observed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                              (eid,sid,cid,rv,vote,pid,rh,t,t))
                bv=q.execute("""SELECT COALESCE(MAX(observation_version),0)+1 AS v FROM ballot_accounting_observations
                               WHERE election_id=%s AND polling_station_id=%s AND position_id=%s""",(eid,sid,pid)).fetchone()["v"]
                bh=hash_input("BALLOT_ACCOUNTING",eid,sid,pid,bv,valid,rejected,spoilt,turnout_value,t.isoformat())
                tid=q.execute("""SELECT turnout_observation_id FROM turnout_observations WHERE election_id=%s AND polling_station_id=%s
                                 ORDER BY observation_version DESC LIMIT 1""",(eid,sid)).fetchone()["turnout_observation_id"]
                q.execute("""INSERT INTO ballot_accounting_observations(election_id,polling_station_id,position_id,observation_version,
                             valid_votes,rejected_votes,spoilt_ballots,turnout_observation_id,observed_at,input_hash)
                             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(eid,sid,pid,bv,valid,rejected,spoilt,tid,t,bh))
                c.commit(); message=f"{pid}: {valid} valid + {rejected} rejected = {turnout_value} turnout; {spoilt} spoilt tracked separately."
            except Exception as exc: c.rollback(); error=True; message=str(exc)
    body=render_template_string("""<section><h2>Contest results + ballot accounting</h2>
    <p class="small"><strong>Turnout is station-wide.</strong> Valid votes are derived from candidate entries for this contest. Spoilt ballots are separate and never counted as cast.</p>
    <form method="get"><div class="grid"><div><label>Polling station</label><select name="polling_station_id" onchange="this.form.submit()"><option value="">Select</option>
    {% for s in stations %}<option value="{{s.polling_station_id}}" {% if s.polling_station_id==sid %}selected{% endif %}>{{s.polling_station_code}} — {{s.polling_station_id}}</option>{% endfor %}</select></div>
    <div><label>Contest</label><select name="position_id" onchange="this.form.submit()"><option value="">Select</option>{% for p in positions %}<option value="{{p.position_id}}" {% if p.position_id==pid %}selected{% endif %}>{{p.position_name}}</option>{% endfor %}</select></div></div></form>
    {% if sid and pid %}{% if turnout_value is none %}<div class="notice error">Enter turnout for this station first.</div>{% else %}
    <div class="notice">Turnout / voters cast: <strong>{{turnout_value}}</strong></div>
    <form method="post"><input type="hidden" name="polling_station_id" value="{{sid}}"><input type="hidden" name="position_id" value="{{pid}}">
    <h3>Candidate votes</h3><table><tr><th>Candidate</th><th>Votes</th></tr>
    {% for x in candidates %}<tr><td>{{x.candidate_name}}</td><td><input name="vote_{{x.candidate_id}}" type="number" min="0" value="0" required></td></tr>{% endfor %}</table>
    <div class="grid"><div><label>Rejected ballots</label><input name="rejected_votes" type="number" min="0" value="0" required></div>
    <div><label>Spoilt ballots (not cast)</label><input name="spoilt_ballots" type="number" min="0" value="0" required></div></div>
    <p class="notice">ETVS calculates <strong>valid votes = total candidate votes</strong> and requires <strong>turnout = valid + rejected</strong>.</p>
    <button type="submit">Save contest results + accounting</button></form>{% endif %}{% endif %}</section>""",
        stations=stations,positions=positions,sid=sid,pid=pid,candidates=candidates,turnout_value=turnout_value)
    return render(body,message,error)

if __name__=="__main__":
    app.run(host=os.getenv("ETVS_WEB_HOST","127.0.0.1"),port=int(os.getenv("ETVS_WEB_PORT","5000")),debug=False)
