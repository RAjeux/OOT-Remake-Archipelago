use std::time::{Duration, Instant};

use ootrr_core::error::{Error as E, Res};

use crate::game::Game;
use crate::gdm;
use crate::snap::Snap;

pub const RETRY: Duration = Duration::from_secs(2);

#[derive(Default)]
pub struct Reader {
    g: Option<Game>,
    tried: Option<Instant>,
    last_err: Option<String>,
}

impl Reader {
    pub fn new() -> Reader {
        Reader::default()
    }

    pub fn attached(&self) -> Option<u32> {
        self.g.as_ref().map(|g| g.pid())
    }

    pub fn exe(&self) -> Option<std::path::PathBuf> {
        self.g.as_ref().and_then(|g| g.exe())
    }

    fn ensure(&mut self, now: Instant) -> Res<&Game> {
        if self.g.as_ref().is_some_and(|g| !g.alive()) {
            self.g = None;
        }
        if self.g.is_none() {
            if self.tried.is_some_and(|t| now.saturating_duration_since(t) < RETRY) {
                return Err(E::Msg(self.last_err.clone().unwrap_or_else(|| "game not running".to_string())));
            }
            self.tried = Some(now);
            match Game::attach() {
                Ok(g) => self.g = Some(g),
                Err(e) => {
                    self.last_err = Some(e.to_string());
                    return Err(e);
                }
            }
        }
        self.g.as_ref().ok_or_else(|| E::Msg("game not running".to_string()))
    }

    pub fn poll(&mut self, now: Instant) -> Res<Snap> {
        let g: &Game = self.ensure(now)?;
        match gdm::snap(g) {
            Ok(s) => Ok(s),
            Err(e) => {
                if !g.alive() {
                    self.g = None;
                    return Err(E::Msg("game not running".to_string()));
                }
                Err(e)
            }
        }
    }
}
