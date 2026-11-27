//! Native cosmetic application over a private, already prepared AP overlay.
use ootrr_core::{colors::{self, Colors}, cosmetic::{self, Cosmetics, Music}, json::Json, sfx::Sfx};
use super::{field, Result};

pub fn parse(request: &Json) -> Result<Cosmetics> {
    let envelope = request.get("features").ok_or("missing feature settings")?;
    if envelope.get("schema").and_then(Json::as_i64) != Some(1) {
        return Err("unsupported cosmetic feature schema".into());
    }
    let features = envelope.get("settings").filter(|settings| settings.as_obj().is_some())
        .ok_or("missing cosmetic settings object")?;
    let value = |name: &str, default: &str| -> Result<String> {
        match features.get(name) {
            None => Ok(default.to_string()),
            Some(Json::Str(s)) => Ok(s.clone()),
            _ => Err(format!("{name} must be a string").into()),
        }
    };
    let music = Music::parse(&value("shuffle_music", "off")?).ok_or("invalid music mode")?;
    let sfx = Sfx::parse(&value("shuffle_sfx", "off")?).ok_or("invalid sound effects mode")?;
    let colors = Colors::parse(&value("cosmetic_color_mode", "off")?).ok_or("invalid color mode")?;
    let mut picks = Vec::new();
    if let Some(parts) = features.get("cosmetic_colors") {
        for (part, color) in parts.as_obj().ok_or("color choices must be an object")? {
            picks.push((part.clone(), color.as_str().ok_or("a color choice must be text")?.to_string()));
        }
    }
    let parts = colors::parse_picks(&picks)?;
    let seed = field(request, "seed")?.to_string();
    if seed.is_empty() || seed.len() > 128 || seed.chars().any(char::is_control) {
        return Err("invalid room cosmetic seed".into());
    }
    // Keep the integration's AP title rather than replacing it with OOTRR's.
    Ok(Cosmetics { music, sfx, colors, seed, title: false, parts })
}

pub fn run(request: &Json) -> Result<()> {
    let options = parse(request)?;
    if options.any() {
        for note in cosmetic::apply(std::path::Path::new("/load/Archipelago"), std::path::Path::new("/game"), &options)? {
            println!("{note}");
        }
    }
    println!("Applied room cosmetics without changing its AP placements.");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cosmetic_seed_is_repeatable_and_never_replaces_the_ap_title() {
        let request = Json::obj().with("seed", "AP-test-room".into()).with("features",
            Json::obj().with("schema", 1_i64.into()).with("settings", Json::obj().with("shuffle_music", "grouped".into())));
        let a = parse(&request).unwrap();
        assert_eq!(a, parse(&request).unwrap());
        assert!(!a.title);
        assert!(parse(&request.clone().with("seed", "\n".into())).is_err());
        let bad = request.clone().with("features", Json::obj().with("schema", 1_i64.into()).with("settings",
            Json::obj().with("cosmetic_colors", Json::obj().with("../Model", "#ffffff".into()))));
        assert!(parse(&bad).is_err());
        let unknown = request.clone().with("features", Json::obj().with("schema", 2_i64.into()).with("settings", Json::obj()));
        assert!(parse(&unknown).is_err());
        let absent = request.with("features", Json::obj().with("settings", Json::obj()));
        assert!(parse(&absent).is_err());
    }
}
