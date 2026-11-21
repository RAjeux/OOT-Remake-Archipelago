use std::collections::{BTreeMap as BM, HashMap as HM, HashSet as HS};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::thread;
use std::time::{Duration, Instant};

use ootrr_core::error::{Error, Res};
use ootrr_core::flags::{self, FlagList};
use ootrr_core::json;
use ootrr_web::tracker::targets::{self, Target};
use ootrr_mem::reader::Reader;
use ootrr_mem::snap::Snap;

const FLAGS: &str = "data/flags.json";
const TICK: Duration = Duration::from_millis(100);
const WARM: Duration = Duration::from_secs(3);
const QUIET: Duration = Duration::from_secs(3);

struct Args {
    flags: String,
    out: Option<String>,
}

fn parse(a: &[String]) -> Res<Args> {
    let mut o: Args = Args { flags: FLAGS.to_string(), out: None };
    let mut i: usize = 0;
    while i < a.len() {
        match a[i].as_str() {
            "--flags" => {
                i += 1;
                o.flags = a.get(i).ok_or(Error::Format("--flags needs a path"))?.clone();
            }
            "--out" => {
                i += 1;
                o.out = Some(a.get(i).ok_or(Error::Format("--out needs a path"))?.clone());
            }
            other => return Err(Error::Msg(format!("unknown option {other}"))),
        }
        i += 1;
    }
    Ok(o)
}

fn names(p: &str) -> Res<HM<u32, (String, String)>> {
    let t: String = fs::read_to_string(p)?;
    let l: FlagList = flags::from_json(&json::parse_with(&t, &json::Limits { depth: 64, bytes: 64 << 20 })?)?;
    let mut out: HM<u32, (String, String)> = HM::new();
    for f in &l.flags {
        let n: String = f.name.clone().unwrap_or_else(|| format!("0x{:08x}", f.hash));
        out.insert(f.hash as u32, (n, f.ty.clone()));
    }
    Ok(out)
}

fn key_names() -> HM<u64, String> {
    let ts: &[Target] = targets::all().unwrap_or(&[]);
    let mut out: HM<u64, String> = HM::new();
    for t in ts {
        for k in t.keys.iter().chain(t.keys2.iter()) {
            out.insert(*k, format!("{} ({})", t.label(), t.ootr.as_deref().unwrap_or("-")));
        }
    }
    out
}

fn emit(f: &mut Option<File>, line: &str) {
    println!("{line}");
    if let Some(f) = f {
        let _ = writeln!(f, "{line}");
        let _ = f.flush();
    }
}

pub fn run(a: &[String]) -> Res<()> {
    let o: Args = parse(a)?;
    let nm: HM<u32, (String, String)> = names(&o.flags)?;
    let kn: HM<u64, String> = key_names();
    let mut f: Option<File> = match &o.out {
        Some(p) => Some(OpenOptions::new().create(true).append(true).open(p)?),
        None => None,
    };
    let mut r: Reader = Reader::new();
    let t0: Instant = Instant::now();
    let mut last: Option<Snap> = None;
    let mut down: Option<String> = None;
    let mut noisy: HS<u32> = HS::new();
    let mut quiet_since: Instant = Instant::now();
    let mut burst: bool = false;
    emit(&mut f, "mem-watch: waiting for the game. Values that change during the first 3 seconds are treated as noise and muted.");
    loop {
        let now: Instant = Instant::now();
        match r.poll(now) {
            Ok(s) => {
                if down.take().is_some() || last.is_none() {
                    emit(&mut f, &format!("[{:>8.1}s] attached to pid {:?}, {} values, {} collected keys", t0.elapsed().as_secs_f32(), r.attached(), s.rows.len(), s.keys.len()));
                }
                if let Some(p) = &last {
                    let old: BM<u32, u32> = p.rows.iter().copied().collect();
                    let warm: bool = now.saturating_duration_since(t0) < WARM;
                    let mut lines: Vec<String> = Vec::new();
                    for (h, v) in &s.rows {
                        let was: u32 = old.get(h).copied().unwrap_or(0);
                        if was == *v {
                            continue;
                        }
                        if warm {
                            noisy.insert(*h);
                            continue;
                        }
                        if noisy.contains(h) {
                            continue;
                        }
                        let (n, ty): (String, String) = nm.get(h).cloned().unwrap_or_else(|| (format!("0x{h:08x}"), "?".to_string()));
                        lines.push(format!("{ty:<6} {n} = {was} -> {v}"));
                    }
                    let ok: HS<u64> = p.keys.iter().copied().collect();
                    let nk: HS<u64> = s.keys.iter().copied().collect();
                    for k in nk.difference(&ok) {
                        lines.push(format!("key +  {k} {}", kn.get(k).map(|x| x.as_str()).unwrap_or("")));
                    }
                    for k in ok.difference(&nk) {
                        lines.push(format!("key -  {k} {}", kn.get(k).map(|x| x.as_str()).unwrap_or("")));
                    }
                    if lines.is_empty() {
                        if burst && now.saturating_duration_since(quiet_since) >= QUIET {
                            emit(&mut f, "");
                            burst = false;
                        }
                    } else {
                        let at: f32 = t0.elapsed().as_secs_f32();
                        for l in lines {
                            emit(&mut f, &format!("[{at:>8.1}s] {l}"));
                        }
                        quiet_since = now;
                        burst = true;
                    }
                }
                last = Some(s);
            }
            Err(e) => {
                let m: String = e.to_string();
                if down.as_deref() != Some(m.as_str()) {
                    emit(&mut f, &format!("[{:>8.1}s] not live: {m}", t0.elapsed().as_secs_f32()));
                    down = Some(m);
                }
                last = None;
            }
        }
        let spent: Duration = now.elapsed();
        if spent < TICK {
            thread::sleep(TICK - spent);
        }
    }
}
