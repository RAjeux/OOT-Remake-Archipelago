#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Conn {
    pub name: &'static str,
    pub area: &'static str,
    pub map: &'static str,
    pub entry: (&'static str, &'static str),
    pub exit: (&'static str, &'static str),
    pub doors: &'static [u64],
    pub back: u64,
    pub extra: &'static [&'static str],
}

pub const DUNGEONS: [Conn; 11] = [
    Conn {
        name: "Deku Tree",
        area: "Kokiri Forest",
        map: "InsideTheDekuTree",
        entry: ("KF Outside Deku Tree", "Deku Tree Lobby"),
        exit: ("Deku Tree Lobby", "KF Outside Deku Tree"),
        doors: &[11591212048579065524, 5055470052273839817],
        back: 7202597688446125475,
        extra: &[],
    },
    Conn {
        name: "Dodongos Cavern",
        area: "Death Mountain Trail",
        map: "DodongoCavern",
        entry: ("Death Mountain", "Dodongos Cavern Beginning"),
        exit: ("Dodongos Cavern Beginning", "Death Mountain"),
        doors: &[7450436466790279046, 14899609633248452346],
        back: 13182986850363170417,
        extra: &[],
    },
    Conn {
        name: "Jabu Jabus Belly",
        area: "Zoras Fountain",
        map: "InsideJabuJabuBelly",
        entry: ("Zoras Fountain", "Jabu Jabus Belly Beginning"),
        exit: ("Jabu Jabus Belly Beginning", "Zoras Fountain"),
        doors: &[4228704915231375030],
        back: 17995796037457417799,
        extra: &[],
    },
    Conn {
        name: "Bottom of the Well",
        area: "Kakariko Village",
        map: "BottomOfTheWell",
        entry: ("Kakariko Village", "Bottom of the Well"),
        exit: ("Bottom of the Well", "Kakariko Village"),
        doors: &[7724348420662166424, 6398355764627578761, 7282308262581659982],
        back: 5879842905123968374,
        extra: &[],
    },
    Conn {
        name: "Forest Temple",
        area: "Sacred Forest Meadow",
        map: "ForestTemple",
        entry: ("SFM Forest Temple Entrance Ledge", "Forest Temple Lobby"),
        exit: ("Forest Temple Lobby", "SFM Forest Temple Entrance Ledge"),
        doors: &[12111229406165987984, 16062333584792453828],
        back: 6424309957238316552,
        extra: &[],
    },
    Conn {
        name: "Fire Temple",
        area: "Death Mountain Crater",
        map: "FireTemple",
        entry: ("DMC Fire Temple Entrance", "Fire Temple Lower"),
        exit: ("Fire Temple Lower", "DMC Fire Temple Entrance"),
        doors: &[5610205918630370402, 7902523242437326635],
        back: 15777142521042929903,
        extra: &[],
    },
    Conn {
        name: "Water Temple",
        area: "Lake Hylia",
        map: "WaterTemple",
        entry: ("Lake Hylia", "Water Temple Lobby"),
        exit: ("Water Temple Lobby", "Lake Hylia"),
        doors: &[17562902631547701330, 1570045424068288510],
        back: 15195247349712517277,
        extra: &[],
    },
    Conn {
        name: "Shadow Temple",
        area: "Graveyard",
        map: "ShadowTemple",
        entry: ("Graveyard Warp Pad Region", "Shadow Temple Entryway"),
        exit: ("Shadow Temple Entryway", "Graveyard Warp Pad Region"),
        doors: &[8073930803580665285, 2492461338144615701],
        back: 18111227224209553662,
        extra: &[],
    },
    Conn {
        name: "Spirit Temple",
        area: "Desert Colossus",
        map: "SpiritTemple",
        entry: ("Desert Colossus", "Spirit Temple Lobby"),
        exit: ("Spirit Temple Lobby", "Desert Colossus From Spirit Lobby"),
        doors: &[13187812046230253833, 15448624735210695325],
        back: 6726536725586102117,
        extra: &["adult", "child"],
    },
    Conn {
        name: "Ice Cavern",
        area: "Zoras Fountain",
        map: "IceCavern",
        entry: ("ZF Ice Ledge", "Ice Cavern Beginning"),
        exit: ("Ice Cavern Beginning", "ZF Ice Ledge"),
        doors: &[3056948024719440641],
        back: 4069798734802445712,
        extra: &["adult"],
    },
    Conn {
        name: "Gerudo Training Ground",
        area: "Gerudo Fortress",
        map: "GerudoTrainingGround",
        entry: ("Gerudo Fortress", "Gerudo Training Ground Lobby"),
        exit: ("Gerudo Training Ground Lobby", "Gerudo Fortress"),
        doors: &[16659021570705780937],
        back: 9849011308940982015,
        extra: &[],
    },
];

pub fn find(name: &str) -> Option<usize> {
    DUNGEONS.iter().position(|c| c.name.eq_ignore_ascii_case(name))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet as BS;

    #[test]
    fn every_actor_is_listed_once_and_names_are_unique() {
        let mut seen: BS<u64> = BS::new();
        let mut names: BS<&str> = BS::new();
        for c in DUNGEONS {
            assert!(names.insert(c.name));
            for h in c.doors.iter().chain([c.back].iter()) {
                assert!(seen.insert(*h), "{h}");
            }
        }
        assert_eq!(find("deku tree"), Some(0));
        assert_eq!(find("Ganons Castle"), None);
    }
}
