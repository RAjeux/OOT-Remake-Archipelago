// Pinned AP-only rule bundle. Legacy generation keeps world_files.rs.
pub const OVERWORLD: [&str; 22] = [
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Spawns and Warps.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Kokiri Forest.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Lost Woods.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Hyrule Field.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Lake Hylia.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Gerudo Valley.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Gerudo Fortress.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Haunted Wasteland.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Desert Colossus.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Market.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Hyrule Castle.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Market Buildings.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Kakariko Village.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Graveyard.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Death Mountain Trail.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Goron City.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Death Mountain Crater.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Zoras River.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Zoras Domain.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Zoras Fountain.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Lon Lon Ranch.json"),
    include_str!("../../../../data/ap_logic_v2/World/Overworld/Grottos.json"),
];

pub const DUNGEONS: [&str; 13] = [
    include_str!("../../../../data/ap_logic_v2/World/Bosses.json"),
    include_str!("../../../../data/ap_logic_v2/World/Deku Tree.json"),
    include_str!("../../../../data/ap_logic_v2/World/Dodongos Cavern.json"),
    include_str!("../../../../data/ap_logic_v2/World/Jabu Jabus Belly.json"),
    include_str!("../../../../data/ap_logic_v2/World/Forest Temple.json"),
    include_str!("../../../../data/ap_logic_v2/World/Fire Temple.json"),
    include_str!("../../../../data/ap_logic_v2/World/Water Temple.json"),
    include_str!("../../../../data/ap_logic_v2/World/Shadow Temple.json"),
    include_str!("../../../../data/ap_logic_v2/World/Spirit Temple.json"),
    include_str!("../../../../data/ap_logic_v2/World/Bottom of the Well.json"),
    include_str!("../../../../data/ap_logic_v2/World/Ice Cavern.json"),
    include_str!("../../../../data/ap_logic_v2/World/Gerudo Training Ground.json"),
    include_str!("../../../../data/ap_logic_v2/World/Ganons Castle.json"),
];

pub fn all() -> Vec<&'static str> {
    OVERWORLD.iter().chain(DUNGEONS.iter()).copied().collect()
}

pub fn overworld_text() -> &'static str {
    static TEXT: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    TEXT.get_or_init(|| OVERWORLD.concat())
}
