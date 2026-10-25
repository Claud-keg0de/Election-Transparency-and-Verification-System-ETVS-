"""ETVS local form-driven source-entry application.

Normal human data entry happens here; seed.py remains a deterministic test
fixture tool rather than the source-entry interface.
"""
from __future__ import annotations
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from datetime import datetime, timezone
import blake3
import psycopg
from flask import Flask, redirect, render_template_string, request, url_for
from psycopg.rows import dict_row

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("ETVS_FLASK_SECRET") or secrets.token_hex(32)
app.jinja_env.autoescape = True
POSITIONS=("POS-PRESIDENT","POS-GOVERNOR","POS-SENATOR","POS-WOMEN-REP","POS-MP","POS-MCA")
CAPTURE_STATES=("PRESENT","BLANK","ILLEGIBLE","NOT_CAPTURED")
SIGNATURE_STATES=("SIGNED","NOT_SIGNED","ILLEGIBLE","NOT_REVIEWED")
ALLOWED_UPLOAD_EXTENSIONS={".pdf",".png",".jpg",".jpeg",".webp"}
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("ETVS_MAX_UPLOAD_BYTES",str(25*1024*1024)))

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
<a href="/">Dashboard</a><a href="/polling-stations/new">Polling Station</a><a href="/form34a">Form 34A Evidence</a><a href="/turnout">Turnout by Position</a><a href="/contest">Results + Ballot Accounting</a>
</nav>{% if message %}<div class="notice {{'error' if error else 'ok'}}">{{message}}</div>{% endif %}{{body|safe}}</body></html>"""

def db():
    return psycopg.connect(host=os.getenv("ETVS_DB_HOST","localhost"),port=int(os.getenv("ETVS_DB_PORT","5432")),
                           dbname=os.getenv("ETVS_DB_NAME","etvs"),user=os.getenv("ETVS_DB_USER","postgres"),
                           password=os.getenv("ETVS_DB_PASSWORD",""),row_factory=dict_row)
def now(): return datetime.now(timezone.utc)
def hash_input(*parts): return blake3.blake3("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()
def result_submission_hash(election_id, station_id, candidate_id, version, votes):
    # Must remain identical to audit_engine.result_hash() so R010 can verify
    # every result submitted through the form.
    return hash_input("RESULT", election_id, station_id, candidate_id, version, votes)
def nonneg(name,value):
    if value is None or value.strip()=="": raise ValueError(f"{name} is required.")
    n=int(value)
    if n<0: raise ValueError(f"{name} cannot be negative.")
    return n

def captured_count(field,label):
    """Return a nullable number and explicit source-field capture state."""
    state=request.form.get(field+"_status","PRESENT").strip().upper()
    if state not in CAPTURE_STATES:
        raise ValueError(f"{label} has an invalid capture state.")
    raw=(request.form.get(field) or "").strip()
    if state=="PRESENT":
        return nonneg(label,raw),state
    if raw:
        raise ValueError(f"{label}: clear the numeric value when state is {state}.")
    return None,state

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
    <section><h2>Source-entry workflow</h2><p><a href="/form34a">Upload and transcribe Form 34A</a> · <a href="/turnout">Record turnout for each position</a> · <a href="/contest">Enter contest results and ballot accounting</a></p><p class="small">Form evidence and normalized observations are stored separately. Turnout values are entered independently for all six electoral positions.</p></section>
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
                existing_rc=q.execute("""SELECT registration_centre_id
                                            FROM registration_centres
                                           WHERE ward_id=%s AND registration_centre_name=%s""",(wid,centre)).fetchone()
                if existing_rc:
                    rcid=existing_rc["registration_centre_id"]
                else:
                    rcid="RC-"+blake3.blake3(f"{wid}|{centre.strip().casefold()}".encode()).hexdigest()[:16].upper()
                    q.execute("""INSERT INTO registration_centres(registration_centre_id,registration_centre_name,ward_id)
                                 VALUES(%s,%s,%s)""",(rcid,centre,wid))
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
        positions=q.execute("SELECT position_id,position_name FROM positions WHERE position_id=ANY(%s) ORDER BY observation_sequence NULLS LAST,position_id",(list(POSITIONS),)).fetchall()
        sid=request.values.get("polling_station_id",""); pid=request.values.get("position_id","")
        if request.method=="POST":
            try:
                sid=request.form["polling_station_id"]; pid=request.form["position_id"]
                if pid not in POSITIONS: raise ValueError("Select a supported electoral position.")
                value=nonneg("Turnout / voters cast",request.form.get("voters_turnout"))
                st=q.execute("SELECT * FROM polling_stations WHERE polling_station_id=%s",(sid,)).fetchone()
                if not st: raise ValueError("Polling station does not exist.")
                if value>st["registered_voters"]: raise ValueError("Position turnout cannot exceed the station's registered-voter reference.")
                previous=q.execute("""SELECT observed_at FROM turnout_observations
                                      WHERE election_id=%s AND polling_station_id=%s AND position_id=%s
                                      ORDER BY observation_version DESC LIMIT 1""",(st["election_id"],sid,pid)).fetchone()
                t=now()
                if previous is not None:
                    elapsed=(t-previous["observed_at"]).total_seconds()/60
                    if elapsed < st["turnout_reporting_interval_minutes"]:
                        raise ValueError(f"Next {pid} turnout observation is not due yet. This station's configured interval is {st['turnout_reporting_interval_minutes']} minutes; only {elapsed:.1f} minutes have elapsed.")
                v=q.execute("""SELECT COALESCE(MAX(observation_version),0)+1 AS v FROM turnout_observations
                               WHERE election_id=%s AND polling_station_id=%s AND position_id=%s""",(st["election_id"],sid,pid)).fetchone()["v"]
                h=hash_input("TURNOUT",st["election_id"],sid,pid,v,value,t.isoformat())
                q.execute("""INSERT INTO turnout_observations(election_id,polling_station_id,position_id,observation_version,
                             voters_turnout,observed_at,input_hash,source_reference)
                             VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                          (st["election_id"],sid,pid,v,value,t,h,"MANUAL_POSITION_TURNOUT"))
                c.commit(); message=f"{pid}: turnout {value} saved for {sid} (observation version {v})."
            except Exception as exc: c.rollback(); error=True; message=str(exc)
    body=render_template_string("""<section><h2>Turnout / votes cast by electoral position</h2>
    <p class="small">Record a separate turnout observation for each polling station and each ballot position: President, Governor, Senator, Woman Representative, MP and MCA. The six figures may differ. ETVS does not copy one position's turnout into another position.</p>
    <form method="post"><div class="grid"><div><label>Polling station</label><select name="polling_station_id" required>{% for s in stations %}<option value="{{s.polling_station_id}}" {% if s.polling_station_id==sid %}selected{% endif %}>{{s.polling_station_code}} — {{s.polling_station_id}} — registered {{s.registered_voters}}</option>{% endfor %}</select></div>
    <div><label>Electoral position / ballot</label><select name="position_id" required>{% for p in positions %}<option value="{{p.position_id}}" {% if p.position_id==pid %}selected{% endif %}>{{p.position_name}} ({{p.position_id}})</option>{% endfor %}</select></div></div>
    <label>Voters who cast a ballot for this position</label><input name="voters_turnout" type="number" min="0" required>
    <p class="small">Enter the value supported by the relevant source. The configured ETVS reporting interval is enforced separately for each station/position stream.</p>
    <button type="submit">Save position turnout</button></form></section>""",stations=stations,positions=positions,sid=sid,pid=pid)
    return render(body,message,error)


@app.route("/form34a",methods=["GET","POST"])
def form34a():
    """Capture a Form 34A source plus a reviewable transcription of its printed fields."""
    message=None; error=False
    with db() as conn,conn.cursor() as q:
        stations=q.execute("""SELECT ps.polling_station_id,ps.polling_station_code,ps.election_id,ps.registered_voters,
                                     e.election_name,w.ward_name,c.constituency_name,co.county_name
                                FROM polling_stations ps JOIN elections e ON e.election_id=ps.election_id
                                JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id
                                JOIN wards w ON w.ward_id=rc.ward_id JOIN constituencies c ON c.constituency_id=w.constituency_id
                                JOIN counties co ON co.county_id=c.county_id
                               ORDER BY co.county_name,c.constituency_name,w.ward_name,ps.polling_station_code""").fetchall()
        sid=request.values.get("polling_station_id","")
        station=next((s for s in stations if s["polling_station_id"]==sid),None)
        candidates=[]
        if station:
            candidates=q.execute("""SELECT candidate_id,candidate_name FROM candidates
                                    WHERE election_id=%s AND position_id='POS-PRESIDENT'
                                    ORDER BY candidate_name""",(station["election_id"],)).fetchall()
        if request.method=="POST":
            try:
                sid=request.form["polling_station_id"].strip()
                station=q.execute("""SELECT ps.*,e.election_name FROM polling_stations ps
                                     JOIN elections e ON e.election_id=ps.election_id
                                     WHERE ps.polling_station_id=%s""",(sid,)).fetchone()
                if not station: raise ValueError("Select a valid polling station.")
                candidates=q.execute("""SELECT candidate_id,candidate_name FROM candidates
                                        WHERE election_id=%s AND position_id='POS-PRESIDENT'
                                        ORDER BY candidate_name""",(station["election_id"],)).fetchall()
                candidate_refs={x["candidate_id"]:x["candidate_name"] for x in candidates}
                upload=request.files.get("form_file")
                if upload is None or not upload.filename: raise ValueError("Upload the original Form 34A PDF or image.")
                safe_name=secure_filename(upload.filename)
                ext=Path(safe_name).suffix.lower()
                if not safe_name or ext not in ALLOWED_UPLOAD_EXTENSIONS:
                    raise ValueError("The Form 34A attachment must be a PDF, PNG, JPG, JPEG or WEBP file.")
                payload=upload.read(app.config["MAX_CONTENT_LENGTH"]+1)
                if not payload: raise ValueError("The uploaded source file is empty.")
                if len(payload)>app.config["MAX_CONTENT_LENGTH"]: raise ValueError("The uploaded file exceeds ETVS_MAX_UPLOAD_BYTES.")
                signatures={
                    ".pdf": payload.startswith(b"%PDF-"),
                    ".png": payload.startswith(b"\x89PNG\r\n\x1a\n"),
                    ".jpg": payload.startswith(b"\xff\xd8\xff"),
                    ".jpeg": payload.startswith(b"\xff\xd8\xff"),
                    ".webp": len(payload)>=12 and payload[:4]==b"RIFF" and payload[8:12]==b"WEBP",
                }
                if not signatures.get(ext,False):
                    raise ValueError("The uploaded file does not match its declared PDF/image type.")
                content_hash=blake3.blake3(payload).hexdigest()
                source_url=(request.form.get("source_url") or "").strip()
                if source_url:
                    parsed=urlparse(source_url)
                    if parsed.scheme not in ("http","https") or not parsed.netloc:
                        raise ValueError("Source URL must be a valid HTTP or HTTPS URL.")
                form_serial=(request.form.get("printed_form_serial") or "").strip() or None
                printed_code=(request.form.get("printed_station_code") or "").strip() or None
                printed_station=(request.form.get("printed_station_name") or "").strip() or None
                printed_ward=(request.form.get("printed_ward_name") or "").strip() or None
                printed_constituency=(request.form.get("printed_constituency_name") or "").strip() or None
                printed_county=(request.form.get("printed_county_name") or "").strip() or None
                source_page_raw=(request.form.get("source_page") or "").strip()
                source_page=nonneg("Source page",source_page_raw) if source_page_raw else None
                if source_page==0: raise ValueError("Source page must be greater than zero.")
                field_values={}
                for field,label in (
                    ("registered_voters_reported","Registered voters printed on Form 34A"),
                    ("candidate_table_valid_total_reported","Candidate-table total valid votes"),
                    ("rejected_ballots_reported","Rejected ballot papers"),
                    ("rejection_objected_to_reported","Rejection-objected-to count"),
                    ("disputed_votes_reported","Disputed votes count"),
                    ("counts_valid_total_reported","Counts-section total valid votes"),
                ):
                    val,state=captured_count(field,label)
                    field_values[field]=val
                    field_values[field.replace("_reported","_status")]=state

                pres_sig=request.form.get("presiding_officer_signature_status","NOT_REVIEWED")
                deputy_sig=request.form.get("deputy_presiding_officer_signature_status","NOT_REVIEWED")
                if pres_sig not in SIGNATURE_STATES or deputy_sig not in SIGNATURE_STATES:
                    raise ValueError("Select a valid signature review state.")
                detail_status=request.form.get("disputed_detail_status","NOT_CAPTURED")
                if detail_status not in ("COMPLETE","PARTIAL","NOT_CAPTURED","NOT_APPLICABLE"):
                    raise ValueError("Select a valid disputed-vote detail state.")

                names=request.form.getlist("candidate_name_printed")
                refs=request.form.getlist("candidate_id")
                vote_values=request.form.getlist("candidate_votes")
                vote_states=request.form.getlist("candidate_votes_status")
                if not names: raise ValueError("Add at least one candidate row from Form 34A.")
                candidate_rows=[]
                seen_refs=set()
                for i,name in enumerate(names):
                    name=(name or "").strip()
                    cid=(refs[i] if i<len(refs) else "").strip() or None
                    raw=(vote_values[i] if i<len(vote_values) else "").strip()
                    state=(vote_states[i] if i<len(vote_states) else "NOT_CAPTURED").strip().upper()
                    if state not in CAPTURE_STATES: raise ValueError(f"Candidate row {i+1} has an invalid vote capture state.")
                    if cid and cid not in candidate_refs: raise ValueError(f"Candidate row {i+1} references a candidate outside this election's presidential contest.")
                    if cid and cid in seen_refs: raise ValueError(f"Candidate {candidate_refs[cid]} appears more than once in this Form 34A capture.")
                    if cid: seen_refs.add(cid)
                    if state=="PRESENT":
                        vote=nonneg(f"Candidate votes (row {i+1})",raw)
                        if not name: name=candidate_refs.get(cid,"").strip()
                        if not name: raise ValueError(f"Candidate row {i+1} needs the printed candidate name.")
                    else:
                        if raw: raise ValueError(f"Clear the candidate vote value in row {i+1} when its capture state is {state}.")
                        vote=None
                        if not name and not cid and state=="NOT_CAPTURED": continue
                        if not name and cid: name=candidate_refs[cid]
                    candidate_rows.append((len(candidate_rows)+1,cid,name,vote,state))
                if not candidate_rows: raise ValueError("At least one candidate row is required.")

                serials=request.form.getlist("disputed_serial")
                serial_states=request.form.getlist("disputed_serial_status")
                assigned_ids=request.form.getlist("disputed_candidate_id")
                assigned_names=request.form.getlist("disputed_candidate_name")
                disputed_rows=[]
                for i,raw_serial in enumerate(serials):
                    serial=(raw_serial or "").strip()
                    state=(serial_states[i] if i<len(serial_states) else "NOT_CAPTURED").strip().upper()
                    cid=(assigned_ids[i] if i<len(assigned_ids) else "").strip() or None
                    name=(assigned_names[i] if i<len(assigned_names) else "").strip() or None
                    if state not in ("PRESENT","ILLEGIBLE","NOT_CAPTURED"):
                        raise ValueError(f"Disputed decision row {i+1} has an invalid serial capture state.")
                    if cid and cid not in candidate_refs: raise ValueError(f"Disputed decision row {i+1} references a non-presidential candidate.")
                    if state=="PRESENT" and not serial: raise ValueError(f"Disputed decision row {i+1} needs a ballot serial number.")
                    if state!="PRESENT" and serial: raise ValueError(f"Clear the serial in disputed decision row {i+1} when state is {state}.")
                    if not serial and not cid and not name and state=="NOT_CAPTURED": continue
                    if cid and not name: name=candidate_refs[cid]
                    disputed_rows.append((len(disputed_rows)+1,serial if state=="PRESENT" else None,state,cid,name))

                upload_root=Path(os.getenv("ETVS_UPLOAD_DIR",str(Path(__file__).resolve().parent.parent/"instance"/"uploads"))).expanduser().resolve()
                target_dir=upload_root/"form34a"/content_hash
                target_dir.mkdir(parents=True,exist_ok=True)
                target=target_dir/safe_name
                if target.exists() and blake3.blake3(target.read_bytes()).hexdigest()!=content_hash:
                    raise ValueError("A file with the same stored name but different bytes already exists.")
                if not target.exists(): target.write_bytes(payload)
                document_uri=f"local-store://form34a/{content_hash}/{safe_name}"
                host=(urlparse(source_url).hostname or "").lower() if source_url else ""
                declared_official=(host=="iebc.or.ke" or host.endswith(".iebc.or.ke"))
                source_type="OFFICIAL" if declared_official else "OTHER"
                source_id="SRC-F34A-"+hash_input(content_hash,source_url)[:20].upper()
                source_name=f"User-submitted Form 34A source {content_hash[:12]}"
                source_description="Uploaded evidence. Source URL and claimed authority are user-provided and have not been independently authenticated."
                q.execute("""INSERT INTO sources(source_id,source_name,source_type,organization_name,description,source_url)
                             VALUES(%s,%s,%s,%s,%s,%s)
                             ON CONFLICT(source_id) DO UPDATE SET source_url=EXCLUDED.source_url,description=EXCLUDED.description""",
                          (source_id,source_name,source_type,"IEBC (declared source; not independently verified)" if declared_official else "User-submitted source",source_description,source_url or None))
                document_name=f"Form34A-{station['polling_station_id']}-{content_hash[:12]}{ext}"
                doc=q.execute("""INSERT INTO source_documents(source_id,document_name,document_type,document_uri,content_hash,hash_algorithm)
                                 VALUES(%s,%s,%s,%s,%s,'BLAKE3-256')
                                 ON CONFLICT(source_id,document_name,content_hash) DO UPDATE SET document_uri=EXCLUDED.document_uri
                                 RETURNING document_id""",
                              (source_id,document_name,"FORM34A_PDF" if ext==".pdf" else "FORM34A_IMAGE",document_uri,content_hash)).fetchone()
                doc_id=doc["document_id"]
                version=q.execute("""SELECT COALESCE(MAX(observation_version),0)+1 AS v FROM form34a_observations
                                     WHERE election_id=%s AND polling_station_id=%s""",(station["election_id"],sid)).fetchone()["v"]
                doc=q.execute("""INSERT INTO form34a_observations(
                    election_id,polling_station_id,source_document_id,observation_version,printed_form_serial,
                    printed_station_code,printed_station_name,printed_ward_name,printed_constituency_name,printed_county_name,
                    registered_voters_reported,registered_voters_status,
                    candidate_table_valid_total_reported,candidate_table_valid_total_status,
                    rejected_ballots_reported,rejected_ballots_status,
                    rejection_objected_to_reported,rejection_objected_to_status,
                    disputed_votes_reported,disputed_votes_status,
                    counts_valid_total_reported,counts_valid_total_status,
                    presiding_officer_signature_status,deputy_presiding_officer_signature_status,
                    disputed_detail_status,extraction_method,review_status,source_page,source_reference)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'MANUAL','UNREVIEWED',%s,%s)
                    RETURNING form34a_observation_id""",
                    (station["election_id"],sid,doc_id,version,form_serial,printed_code,printed_station,printed_ward,printed_constituency,printed_county,
                     field_values["registered_voters_reported"],field_values["registered_voters_status"],
                     field_values["candidate_table_valid_total_reported"],field_values["candidate_table_valid_total_status"],
                     field_values["rejected_ballots_reported"],field_values["rejected_ballots_status"],
                     field_values["rejection_objected_to_reported"],field_values["rejection_objected_to_status"],
                     field_values["disputed_votes_reported"],field_values["disputed_votes_status"],
                     field_values["counts_valid_total_reported"],field_values["counts_valid_total_status"],
                     pres_sig,deputy_sig,detail_status,source_page,f"Uploaded {safe_name}; BLAKE3-256 {content_hash}")).fetchone()
                observation_id=doc["form34a_observation_id"]
                for row_no,cid,name,vote,state in candidate_rows:
                    q.execute("""INSERT INTO form34a_candidate_votes(form34a_observation_id,election_id,row_number,candidate_id,candidate_name_printed,votes_reported,votes_status,source_reference)
                                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                              (observation_id,station["election_id"],row_no,cid,name,vote,state,f"Form 34A candidate row {row_no}"))
                for row_no,serial,state,cid,name in disputed_rows:
                    q.execute("""INSERT INTO form34a_disputed_vote_decisions(form34a_observation_id,election_id,row_number,ballot_serial_number,serial_capture_status,assigned_candidate_id,assigned_candidate_name_printed,source_reference)
                                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                              (observation_id,station["election_id"],row_no,serial,state,cid,name,f"Form 34A disputed-vote decision row {row_no}"))
                conn.commit()
                message=f"Form 34A evidence saved for {sid}: observation {observation_id}, source document {doc_id}. Audit status remains UNREVIEWED until source values are reviewed."
            except Exception as exc:
                conn.rollback(); error=True; message=str(exc)
        recent_forms=q.execute("""
            SELECT f.form34a_observation_id,f.election_id,f.observation_version,f.printed_form_serial,
                   f.review_status,f.reviewed_by,f.created_at,d.document_name,d.content_hash,
                   ps.polling_station_code,ps.polling_station_id
            FROM form34a_observations f
            JOIN source_documents d ON d.document_id=f.source_document_id
            JOIN polling_stations ps ON ps.polling_station_id=f.polling_station_id AND ps.election_id=f.election_id
            ORDER BY f.created_at DESC,f.form34a_observation_id DESC
            LIMIT 30
        """).fetchall()
    body=render_template_string("""<section><h2>Capture Form 34A evidence</h2>
    <p class="notice">Upload the original Form 34A PDF or scan, then transcribe exactly what is printed. ETVS stores the file locally and records its BLAKE3-256 hash. Uploaded files and source URLs are not independently authenticated. The original evidence and the transcription remain separate.</p>
    <form method="post" enctype="multipart/form-data">
    <div class="grid"><div><label>Election / polling station</label><select name="polling_station_id" required><option value="">Select station</option>{% for s in stations %}<option value="{{s.polling_station_id}}" {% if s.polling_station_id==sid %}selected{% endif %}>{{s.election_name}} — {{s.county_name}} / {{s.constituency_name}} / {{s.ward_name}} — {{s.polling_station_code}} ({{s.polling_station_id}})</option>{% endfor %}</select></div>
    <div><label>Original Form 34A PDF / image</label><input type="file" name="form_file" accept=".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp" required><p class="small">Maximum size: {{max_upload_mb}} MB. Storage root is configurable with ETVS_UPLOAD_DIR.</p></div>
    <div><label>Source URL (optional)</label><input name="source_url" type="url" placeholder="https://www.iebc.or.ke/..."></div>
    <div><label>Printed form serial number</label><input name="printed_form_serial"></div>
    <div><label>Printed polling-station code</label><input name="printed_station_code" value="{{station.polling_station_code if station else ''}}"></div>
    <div><label>Printed polling-station name</label><input name="printed_station_name"></div>
    <div><label>Printed ward name</label><input name="printed_ward_name"></div>
    <div><label>Printed constituency name</label><input name="printed_constituency_name"></div>
    <div><label>Printed county name</label><input name="printed_county_name"></div>
    <div><label>Source PDF page (if known)</label><input name="source_page" type="number" min="1"></div></div>
    <h3>Polling-station counts</h3><p class="small">For each count, choose PRESENT and enter a non-negative integer (including 0), or choose BLANK / ILLEGIBLE / NOT_CAPTURED and leave the numeric field empty. Missing and illegible values are not stored as zero.</p>
    {% for field,label in fields %}<div class="grid"><div><label>{{label}}</label><input name="{{field}}" class="capture-value" type="number" min="0"><select class="capture-state" name="{{field}}_status">{% for st in capture_states %}<option value="{{st}}" {% if st=='PRESENT' %}selected{% endif %}>{{st.replace('_',' ')}}</option>{% endfor %}</select></div></div>{% endfor %}
    <h3>Candidate votes</h3><p class="small">Known presidential candidates are prefilled from election reference data. Verify each printed name and enter its value. Add an unmatched row if the source cannot be mapped confidently.</p>
    <table><thead><tr><th>Candidate name as printed</th><th>Canonical match (optional)</th><th>Votes</th><th>Capture state</th></tr></thead><tbody id="candidate-rows">
    {% for x in candidates %}<tr class="candidate-row"><td><input class="candidate-name" name="candidate_name_printed" value="{{x.candidate_name}}"></td><td><select name="candidate_id"><option value="">Unmatched / review</option>{% for y in candidates %}<option value="{{y.candidate_id}}" {% if y.candidate_id==x.candidate_id %}selected{% endif %}>{{y.candidate_name}}</option>{% endfor %}</select></td><td><input class="candidate-votes" name="candidate_votes" type="number" min="0"></td><td><select class="candidate-state" name="candidate_votes_status">{% for st in capture_states %}<option value="{{st}}" {% if st=='PRESENT' %}selected{% endif %}>{{st.replace('_',' ')}}</option>{% endfor %}</select></td></tr>{% endfor %}
    {% if not candidates %}<tr class="candidate-row"><td><input class="candidate-name" name="candidate_name_printed"></td><td><select name="candidate_id"><option value="">Unmatched / review</option></select></td><td><input class="candidate-votes" name="candidate_votes" type="number" min="0"></td><td><select class="candidate-state" name="candidate_votes_status">{% for st in capture_states %}<option value="{{st}}" {% if st=='PRESENT' %}selected{% endif %}>{{st.replace('_',' ')}}</option>{% endfor %}</select></td></tr>{% endif %}
    </tbody></table><button type="button" onclick="addCandidateRow()">Add candidate row</button>
    <template id="candidate-row-template"><tr class="candidate-row"><td><input class="candidate-name" name="candidate_name_printed"></td><td><select name="candidate_id"><option value="">Unmatched / review</option>{% for y in candidates %}<option value="{{y.candidate_id}}">{{y.candidate_name}}</option>{% endfor %}</select></td><td><input class="candidate-votes" name="candidate_votes" type="number" min="0"></td><td><select class="candidate-state" name="candidate_votes_status">{% for st in capture_states %}<option value="{{st}}" {% if st=='PRESENT' %}selected{% endif %}>{{st.replace('_',' ')}}</option>{% endfor %}</select></td></tr></template>
    <h3>Declaration/signatures and disputed-vote detail</h3><div class="grid"><div><label>Presiding officer signature</label><select name="presiding_officer_signature_status">{% for st in signature_states %}<option value="{{st}}">{{st.replace('_',' ')}}</option>{% endfor %}</select></div><div><label>Deputy presiding officer signature</label><select name="deputy_presiding_officer_signature_status">{% for st in signature_states %}<option value="{{st}}">{{st.replace('_',' ')}}</option>{% endfor %}</select></div><div><label>Disputed-vote decision detail completeness</label><select name="disputed_detail_status"><option value="NOT_CAPTURED">Not captured</option><option value="COMPLETE">Complete</option><option value="PARTIAL">Partial</option><option value="NOT_APPLICABLE">Not applicable</option></select></div></div>
    <p class="small">Record individual ballot serial/candidate assignments only where visible on the source. The aggregate disputed count is not a substitute for those details.</p>
    <table><thead><tr><th>Ballot serial as printed</th><th>Serial state</th><th>Assigned candidate</th><th>Printed name if unmatched</th></tr></thead><tbody id="disputed-rows"><tr class="disputed-row"><td><input name="disputed_serial"></td><td><select name="disputed_serial_status"><option value="NOT_CAPTURED">Not captured</option><option value="PRESENT">Present</option><option value="ILLEGIBLE">Illegible</option></select></td><td><select name="disputed_candidate_id"><option value="">Unmatched / review</option>{% for x in candidates %}<option value="{{x.candidate_id}}">{{x.candidate_name}}</option>{% endfor %}</select></td><td><input name="disputed_candidate_name"></td></tr></tbody></table>
    <button type="button" onclick="addDisputedRow()">Add disputed-vote row</button>
    <template id="disputed-row-template"><tr class="disputed-row"><td><input name="disputed_serial"></td><td><select name="disputed_serial_status"><option value="NOT_CAPTURED">Not captured</option><option value="PRESENT">Present</option><option value="ILLEGIBLE">Illegible</option></select></td><td><select name="disputed_candidate_id"><option value="">Unmatched / review</option>{% for x in candidates %}<option value="{{x.candidate_id}}">{{x.candidate_name}}</option>{% endfor %}</select></td><td><input name="disputed_candidate_name"></td></tr></template>
    <button type="submit">Save Form 34A source and transcription</button></form></section>
    <section><h3>Recent Form 34A records</h3>
    <p class="small">Review attribution records the name entered by the local operator; it is not authenticated identity.</p>
    <table><thead><tr><th>Station / observation</th><th>Source</th><th>Review status</th><th>Review action</th></tr></thead><tbody>
    {% for f in recent_forms %}<tr><td>{{f.polling_station_code}}<br><span class="small">{{f.election_id}} · observation {{f.form34a_observation_id}} · version {{f.observation_version}}</span></td>
    <td>{{f.document_name}}<br><span class="small">BLAKE3-256 {{f.content_hash[:16]}}…</span></td>
    <td>{{f.review_status}}{% if f.reviewed_by %}<br><span class="small">by {{f.reviewed_by}}</span>{% endif %}</td>
    <td>{% if f.review_status!='REVIEWED' %}<form method="post" action="/form34a/{{f.form34a_observation_id}}/review" class="review-form">
    <input name="reviewer_name" required placeholder="Reviewer name">
    <input name="review_notes" placeholder="Review note (optional)">
    <button type="submit">Mark reviewed</button></form>{% else %}<span class="small">Reviewed</span>{% endif %}</td></tr>
    {% else %}<tr><td colspan="4">No Form 34A evidence has been captured yet.</td></tr>{% endfor %}
    </tbody></table></section>
    <script>
    function syncCapture(box){
      const state=box.querySelector('.capture-state');
      const value=box.querySelector('.capture-value');
      if(state&&value)value.required=state.value==='PRESENT';
    }
    function syncCandidate(row){
      const state=row.querySelector('.candidate-state');
      const value=row.querySelector('.candidate-votes');
      const name=row.querySelector('.candidate-name');
      if(state&&value)value.required=state.value==='PRESENT';
      if(state&&name)name.required=state.value==='PRESENT';
    }
    document.querySelectorAll('.capture-state').forEach(el=>{
      syncCapture(el.closest('div'));
      el.addEventListener('change',()=>syncCapture(el.closest('div')));
    });
    document.querySelectorAll('.candidate-row').forEach(syncCandidate);
    document.addEventListener('change',e=>{
      if(e.target.classList.contains('candidate-state'))syncCandidate(e.target.closest('.candidate-row'));
    });
    function addCandidateRow(){
      document.getElementById('candidate-rows').appendChild(document.getElementById('candidate-row-template').content.cloneNode(true));
      document.querySelectorAll('.candidate-row').forEach(syncCandidate);
    }
    function addDisputedRow(){
      document.getElementById('disputed-rows').appendChild(document.getElementById('disputed-row-template').content.cloneNode(true));
    }
    </script>""",stations=stations,sid=sid,station=station,candidates=candidates,recent_forms=recent_forms,fields=(
        ("registered_voters_reported","Registered voters"),
        ("candidate_table_valid_total_reported","Candidate table total valid votes"),
        ("rejected_ballots_reported","Rejected ballot papers"),
        ("rejection_objected_to_reported","Rejection objected to"),
        ("disputed_votes_reported","Disputed votes"),
        ("counts_valid_total_reported","Counts-section total valid votes"),
    ),capture_states=CAPTURE_STATES,signature_states=SIGNATURE_STATES,max_upload_mb=app.config["MAX_CONTENT_LENGTH"]//(1024*1024))
    return render(body,message,error)


@app.post("/form34a/<int:observation_id>/review")
def review_form34a(observation_id:int):
    """Record a local human review with an append-only event."""
    reviewer=(request.form.get("reviewer_name") or "").strip()
    notes=(request.form.get("review_notes") or "").strip() or None
    if not reviewer:
        return render("<section><h2>Review not saved</h2><p>A reviewer name is required.</p><p><a href='/form34a'>Return to Form 34A</a></p></section>",
                      "Enter a reviewer name.",True),400
    if len(reviewer)>200 or (notes and len(notes)>4000):
        return render("<section><h2>Review not saved</h2><p>Reviewer name or note exceeds the allowed length.</p><p><a href='/form34a'>Return to Form 34A</a></p></section>",
                      "Reviewer name must be at most 200 characters and notes at most 4000 characters.",True),400
    with db() as conn,conn.cursor() as q:
        form=q.execute("""SELECT form34a_observation_id,election_id,polling_station_id,review_status
                          FROM form34a_observations WHERE form34a_observation_id=%s FOR UPDATE""",
                       (observation_id,)).fetchone()
        if form is None:
            return render("<section><h2>Form 34A not found</h2><p><a href='/form34a'>Return to Form 34A</a></p></section>",
                          "The requested Form 34A observation does not exist.",True),404
        timestamp=now()
        q.execute("""UPDATE form34a_observations
                     SET review_status='REVIEWED',reviewed_by=%s,reviewed_at=%s,review_notes=%s
                     WHERE form34a_observation_id=%s""",
                  (reviewer,timestamp,notes,observation_id))
        q.execute("""INSERT INTO form34a_review_events(
                       form34a_observation_id,election_id,previous_review_status,new_review_status,
                       reviewer_name,review_notes,reviewed_at)
                     VALUES(%s,%s,%s,'REVIEWED',%s,%s,%s)""",
                  (observation_id,form["election_id"],form["review_status"],reviewer,notes,timestamp))
        conn.commit()
        sid=form["polling_station_id"]
    return redirect(url_for("form34a",polling_station_id=sid))




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
                               ORDER BY observation_sequence NULLS LAST,position_id""",(list(POSITIONS),)).fetchall()
        sid=request.values.get("polling_station_id"); pid=request.values.get("position_id")
        candidates=[]; turnout_value=None; turnout_observation_id=None
        if sid:
            st=q.execute("SELECT election_id FROM polling_stations WHERE polling_station_id=%s",(sid,)).fetchone()
            if st and pid in POSITIONS:
                t=q.execute("""SELECT turnout_observation_id,voters_turnout FROM turnout_observations
                               WHERE election_id=%s AND polling_station_id=%s AND position_id=%s
                               ORDER BY observation_version DESC LIMIT 1""",(st["election_id"],sid,pid)).fetchone()
                turnout_value=t["voters_turnout"] if t else None
                turnout_observation_id=t["turnout_observation_id"] if t else None
                candidates=q.execute("""SELECT candidate_id,candidate_name FROM candidates WHERE election_id=%s AND position_id=%s
                                        ORDER BY candidate_name""",(st["election_id"],pid)).fetchall()
        if request.method=="POST":
            try:
                if not sid or not pid or pid not in POSITIONS: raise ValueError("Select a polling station and electoral position.")
                if turnout_value is None or turnout_observation_id is None:
                    raise ValueError("Record a turnout observation for this station and position before entering its contest accounting.")
                rejected=nonneg("Rejected ballots",request.form.get("rejected_votes"))
                spoilt=nonneg("Spoilt ballots",request.form.get("spoilt_ballots"))
                if not candidates: raise ValueError("No candidate reference rows are configured for this election and position.")
                votes={x["candidate_id"]:nonneg(x["candidate_name"],request.form.get("vote_"+x["candidate_id"])) for x in candidates}
                valid=sum(votes.values())
                if valid+rejected != turnout_value:
                    raise ValueError(f"{pid} turnout {turnout_value} must equal valid votes {valid} + rejected ballots {rejected}. Spoilt ballots are tracked separately and excluded from turnout.")
                eid=q.execute("SELECT election_id FROM polling_stations WHERE polling_station_id=%s",(sid,)).fetchone()["election_id"]; t=now()
                for cid,vote in votes.items():
                    rv=q.execute("""SELECT COALESCE(MAX(result_version),0)+1 AS v FROM result_submissions
                                    WHERE election_id=%s AND polling_station_id=%s AND candidate_id=%s""",(eid,sid,cid)).fetchone()["v"]
                    rh=result_submission_hash(eid,sid,cid,rv,vote)
                    q.execute("""INSERT INTO result_submissions(election_id,polling_station_id,candidate_id,result_version,votes,position_id,
                                 submission_hash,submitted_at,observed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                              (eid,sid,cid,rv,vote,pid,rh,t,t))
                bv=q.execute("""SELECT COALESCE(MAX(observation_version),0)+1 AS v FROM ballot_accounting_observations
                               WHERE election_id=%s AND polling_station_id=%s AND position_id=%s""",(eid,sid,pid)).fetchone()["v"]
                bh=hash_input("BALLOT_ACCOUNTING",eid,sid,pid,bv,valid,rejected,spoilt,turnout_observation_id,t.isoformat())
                q.execute("""INSERT INTO ballot_accounting_observations(election_id,polling_station_id,position_id,observation_version,
                             valid_votes,rejected_votes,spoilt_ballots,turnout_observation_id,observed_at,input_hash)
                             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                          (eid,sid,pid,bv,valid,rejected,spoilt,turnout_observation_id,t,bh))
                c.commit(); message=f"{pid}: {valid} valid + {rejected} rejected = turnout {turnout_value}; {spoilt} spoilt ballots tracked separately."
            except Exception as exc: c.rollback(); error=True; message=str(exc)
    body=render_template_string("""<section><h2>Contest results + ballot accounting</h2>
    <p class="small"><strong>Turnout is position-specific.</strong> Record turnout separately for the President, Governor, Senator, Woman Representative, MP and MCA. The selected position's turnout is used for its ballot-accounting reconciliation; values are never shared across positions.</p>
    <form method="get"><div class="grid"><div><label>Polling station</label><select name="polling_station_id" onchange="this.form.submit()"><option value="">Select</option>
    {% for s in stations %}<option value="{{s.polling_station_id}}" {% if s.polling_station_id==sid %}selected{% endif %}>{{s.polling_station_code}} — {{s.polling_station_id}}</option>{% endfor %}</select></div>
    <div><label>Electoral position</label><select name="position_id" onchange="this.form.submit()"><option value="">Select</option>{% for p in positions %}<option value="{{p.position_id}}" {% if p.position_id==pid %}selected{% endif %}>{{p.position_name}}</option>{% endfor %}</select></div></div></form>
    {% if sid and pid %}{% if turnout_value is none %}<div class="notice error">No turnout has been recorded for this station and position. <a href="/turnout?polling_station_id={{sid}}&position_id={{pid}}">Record its turnout first</a>.</div>{% else %}
    <div class="notice">Turnout for {{pid}}: <strong>{{turnout_value}}</strong></div>
    <form method="post"><input type="hidden" name="polling_station_id" value="{{sid}}"><input type="hidden" name="position_id" value="{{pid}}">
    <h3>Candidate votes</h3><table><tr><th>Candidate</th><th>Votes</th></tr>
    {% for x in candidates %}<tr><td>{{x.candidate_name}}</td><td><input name="vote_{{x.candidate_id}}" type="number" min="0" value="0" required></td></tr>{% endfor %}</table>
    <div class="grid"><div><label>Rejected ballots</label><input name="rejected_votes" type="number" min="0" value="0" required></div>
    <div><label>Spoilt ballots (not cast)</label><input name="spoilt_ballots" type="number" min="0" value="0" required></div></div>
    <p class="notice">ETVS calculates <strong>valid votes = total candidate votes</strong> and requires <strong>selected-position turnout = valid + rejected</strong>. Spoilt ballots are not added to turnout.</p>
    <button type="submit">Save contest results + accounting</button></form>{% endif %}{% endif %}</section>""",
        stations=stations,positions=positions,sid=sid,pid=pid,candidates=candidates,turnout_value=turnout_value)
    return render(body,message,error)


if __name__=="__main__":
    app.run(host=os.getenv("ETVS_WEB_HOST","127.0.0.1"),port=int(os.getenv("ETVS_WEB_PORT","5000")),debug=False)
