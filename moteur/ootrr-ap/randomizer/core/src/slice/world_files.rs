pub const OVERWORLD: [&str; 22] = [
    include_str!("../../../../data/logic/World/Overworld/Spawns and Warps.json"),
    include_str!("../../../../data/logic/World/Overworld/Kokiri Forest.json"),
    include_str!("../../../../data/logic/World/Overworld/Lost Woods.json"),
    include_str!("../../../../data/logic/World/Overworld/Hyrule Field.json"),
    include_str!("../../../../data/logic/World/Overworld/Lake Hylia.json"),
    include_str!("../../../../data/logic/World/Overworld/Gerudo Valley.json"),
    include_str!("../../../../data/logic/World/Overworld/Gerudo Fortress.json"),
    include_str!("../../../../data/logic/World/Overworld/Haunted Wasteland.json"),
    include_str!("../../../../data/logic/World/Overworld/Desert Colossus.json"),
    include_str!("../../../../data/logic/World/Overworld/Market.json"),
    include_str!("../../../../data/logic/World/Overworld/Hyrule Castle.json"),
    include_str!("../../../../data/logic/World/Overworld/Market Buildings.json"),
    include_str!("../../../../data/logic/World/Overworld/Kakariko Village.json"),
    include_str!("../../../../data/logic/World/Overworld/Graveyard.json"),
    include_str!("../../../../data/logic/World/Overworld/Death Mountain Trail.json"),
    include_str!("../../../../data/logic/World/Overworld/Goron City.json"),
    include_str!("../../../../data/logic/World/Overworld/Death Mountain Crater.json"),
    include_str!("../../../../data/logic/World/Overworld/Zoras River.json"),
    include_str!("../../../../data/logic/World/Overworld/Zoras Domain.json"),
    include_str!("../../../../data/logic/World/Overworld/Zoras Fountain.json"),
    include_str!("../../../../data/logic/World/Overworld/Lon Lon Ranch.json"),
    include_str!("../../../../data/logic/World/Overworld/Grottos.json"),
];

pub const DUNGEONS: [&str; 13] = [
    include_str!("../../../../data/logic/World/Bosses.json"),
    include_str!("../../../../data/logic/World/Deku Tree.json"),
    include_str!("../../../../data/logic/World/Dodongos Cavern.json"),
    include_str!("../../../../data/logic/World/Jabu Jabus Belly.json"),
    include_str!("../../../../data/logic/World/Forest Temple.json"),
    include_str!("../../../../data/logic/World/Fire Temple.json"),
    include_str!("../../../../data/logic/World/Water Temple.json"),
    include_str!("../../../../data/logic/World/Shadow Temple.json"),
    include_str!("../../../../data/logic/World/Spirit Temple.json"),
    include_str!("../../../../data/logic/World/Bottom of the Well.json"),
    include_str!("../../../../data/logic/World/Ice Cavern.json"),
    include_str!("../../../../data/logic/World/Gerudo Training Ground.json"),
    include_str!("../../../../data/logic/World/Ganons Castle.json"),
];

pub fn all() -> Vec<&'static str> {
    OVERWORLD.iter().chain(DUNGEONS.iter()).copied().collect()
}

pub fn overworld_text() -> &'static str {
    static TEXT: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    TEXT.get_or_init(|| OVERWORLD.concat())
}
