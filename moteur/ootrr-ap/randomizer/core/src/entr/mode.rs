use crate::error::{Error as E, Res};
use crate::settings::Settings;

pub const SETTING: &str = "shuffle_entrances";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Off,
    Dungeons,
    Overworld,
    Everything,
}

impl Mode {
    pub fn id(self) -> &'static str {
        match self {
            Mode::Off => "off",
            Mode::Dungeons => "dungeons",
            Mode::Overworld => "overworld",
            Mode::Everything => "everything",
        }
    }
}

pub const NOT_YET: &str = "this build can only shuffle the dungeon entrances so far. The overworld transitions need their own pool, a return pairing for every age and Alternative map, and a check of the Epona, owl and story arrival scenes, and none of that is built or tested yet. Pick Dungeons or Off";

pub fn parse(v: &str) -> Res<Mode> {
    match v {
        "off" => Ok(Mode::Off),
        "dungeons" => Ok(Mode::Dungeons),
        "overworld" => Ok(Mode::Overworld),
        "everything" => Ok(Mode::Everything),
        o => Err(E::Msg(format!("{SETTING} is {o}, which is not a known choice"))),
    }
}

pub fn read(s: &Settings) -> Res<Mode> {
    let m: Mode = match s.get(SETTING) {
        None => Mode::Off,
        Some(_) => parse(s.text(SETTING)?)?,
    };
    match m {
        Mode::Overworld | Mode::Everything => Err(E::Msg(format!("This build cannot apply these settings yet:\n  {SETTING} is {}, {NOT_YET}.", m.id()))),
        _ => Ok(m),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::settings::Value;

    #[test]
    fn off_by_default_and_unsupported_modes_are_refused_by_name() {
        let mut s: Settings = Settings::default();
        assert_eq!(read(&s).unwrap(), Mode::Off);
        s.set(SETTING, Value::s("dungeons")).unwrap();
        assert_eq!(read(&s).unwrap(), Mode::Dungeons);
        for v in ["overworld", "everything"] {
            s.set(SETTING, Value::s(v)).unwrap();
            let e: String = read(&s).err().unwrap().to_string();
            assert!(e.contains(&format!("{SETTING} is {v}")) && e.contains("Pick Dungeons or Off"), "{e}");
        }
        assert!(parse("sideways").is_err());
    }
}
