pub mod dpad;
pub mod give;
pub mod pool;
pub mod stage;
pub mod table;

pub use give::{read, Kit, Set, Take};

const GEAR: &[(&str, &str, &str)] = &[
    ("kokiri_sword", "Kokiri Sword", "Weapon_Sword_Kokiri"),
    ("deku_shield", "Deku Shield", "Weapon_Shield_Deku"),
    ("slingshot", "Slingshot", "Weapon_Range_SlingShot"),
];

fn gear_row(id: &str) -> Option<&'static (&'static str, &'static str, &'static str)> {
    let key: &str = match table::opt(id) {
        Some(o) if o.group == "slingshot" => "slingshot",
        _ => id,
    };
    GEAR.iter().find(|(k, _, _)| *k == key)
}

#[derive(Debug, Clone, PartialEq)]
pub struct Start {
    pub reward: crate::start_reward::Reward,
    pub gear: Vec<&'static str>,
    pub pouch: Vec<&'static str>,
    pub owned: Vec<&'static str>,
}

impl Start {
    pub fn read(s: &crate::settings::Settings, bad: &mut Vec<String>) -> Start {
        use crate::start_reward::Reward;
        let reward: Reward = match s.text("start_reward") {
            Ok("off") => Reward::Off,
            Ok("stone") => Reward::Stone,
            Ok("medal") => Reward::Medal,
            Ok("any") => Reward::Any,
            Ok(v) => {
                bad.push(format!("start_reward is {v}, which is not a known choice"));
                Reward::Off
            }
            Err(e) => {
                bad.push(e.to_string());
                Reward::Off
            }
        };
        let chosen: Vec<String> = s.items("starting_items").map(|v| v.to_vec()).unwrap_or_default();
        let mut gear: Vec<&'static str> = Vec::new();
        let mut pouch: Vec<&'static str> = Vec::new();
        for id in &chosen {
            if let Some((_, logic, actor)) = gear_row(id)
                && !pouch.contains(actor)
            {
                gear.push(*logic);
                pouch.push(*actor);
            }
        }
        let owned: Vec<&'static str> = chosen.iter().filter_map(|id| table::opt(id)).filter_map(|o| table::group(o.group)).map(|g| g.logic).collect();
        Start { reward, gear, pouch, owned }
    }
}
