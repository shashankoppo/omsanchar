use std::{
    collections::{BTreeMap, HashMap, VecDeque},
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use biscuit_auth::{
    builder::{self, AuthorizerBuilder, BiscuitBuilder, BlockBuilder, Scope},
    Algorithm, AuthorizerLimits, Biscuit, KeyPair, PublicKey,
};
use rand::{rngs::StdRng, SeedableRng};
use sha2::{Digest, Sha256};

const MAX_CACHE_ENTRIES: usize = 8_192;
const CACHE_TTL: Duration = Duration::from_secs(600);
const MAX_REVOKED_ENTRIES: usize = 8_192;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Grant {
    pub tenant: String,
    pub model: String,
    pub budget_microcredits: i64,
    pub max_output_tokens: i64,
    pub expires_at_unix_seconds: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RequestScope {
    pub tenant: String,
    pub model: String,
    pub requested_budget_microcredits: i64,
    pub requested_output_tokens: i64,
}

#[derive(Debug, PartialEq, Eq)]
pub enum TokenError {
    InvalidInput(&'static str),
    InvalidToken,
    Unauthorized,
    Revoked,
    RevocationCapacity,
    Internal,
}

#[derive(Clone)]
struct CacheEntry {
    scope: RequestScope,
    expires_at: SystemTime,
    token_expires_at: SystemTime,
}

struct RevokedEntry;

#[derive(Default)]
struct VerificationCache {
    entries: HashMap<[u8; 32], CacheEntry>,
    insertion_order: VecDeque<[u8; 32]>,
    expiry_order: BTreeMap<(SystemTime, [u8; 32]), ()>,
    evictions: u64,
}

#[derive(Default)]
struct RevocationList {
    entries: HashMap<[u8; 32], RevokedEntry>,
    expiry_order: BTreeMap<(SystemTime, [u8; 32]), ()>,
}

pub struct TokenAuthority {
    root: KeyPair,
    public: PublicKey,
    cache: Mutex<VerificationCache>,
    revoked: Mutex<RevocationList>,
    cache_hits: AtomicU64,
}

impl TokenAuthority {
    pub fn from_secret(secret: &[u8]) -> Result<Self, TokenError> {
        if secret.len() < 32 {
            return Err(TokenError::InvalidInput(
                "the Biscuit root key must contain at least 32 bytes",
            ));
        }
        let seed: [u8; 32] = Sha256::digest(secret).into();
        let mut rng = StdRng::from_seed(seed);
        let root = KeyPair::new_with_rng(Algorithm::Ed25519, &mut rng);
        let public = root.public();
        Ok(Self {
            root,
            public,
            cache: Mutex::new(VerificationCache::default()),
            revoked: Mutex::new(RevocationList::default()),
            cache_hits: AtomicU64::new(0),
        })
    }

    pub fn mint(&self, grant: &Grant) -> Result<String, TokenError> {
        validate_grant(grant)?;
        let expires = i64::try_from(grant.expires_at_unix_seconds)
            .map_err(|_| TokenError::InvalidInput("expiry is out of range"))?;
        let code = r#"
            right("om-sanchar", "invoke");
            tenant0({tenant});
            model0({model});
            quota0({budget});
            max_output0({max_output});
            expires_unix0({expires});
            check if request_tenant($requested), tenant0($allowed), $requested == $allowed;
            check if request_model($requested), model0($allowed), $requested == $allowed;
            check if request_budget($requested), quota0($allowed), $requested <= $allowed;
            check if request_output($requested), max_output0($allowed), $requested <= $allowed;
            check if request_time($now), expires_unix0($expiry), $now < $expiry;
        "#;
        let params = HashMap::from([
            ("tenant".to_owned(), builder::string(&grant.tenant)),
            ("model".to_owned(), builder::string(&grant.model)),
            ("budget".to_owned(), builder::int(grant.budget_microcredits)),
            (
                "max_output".to_owned(),
                builder::int(grant.max_output_tokens),
            ),
            ("expires".to_owned(), builder::int(expires)),
        ]);
        let token = BiscuitBuilder::new()
            .code_with_params(code, params, HashMap::new())
            .map_err(|_| TokenError::Internal)?
            .build(&self.root)
            .map_err(|_| TokenError::Internal)?;
        token.to_base64().map_err(|_| TokenError::Internal)
    }

    pub fn attenuate(&self, encoded: &str, narrower: &Grant) -> Result<String, TokenError> {
        validate_grant(narrower)?;
        let expires = i64::try_from(narrower.expires_at_unix_seconds)
            .map_err(|_| TokenError::InvalidInput("expiry is out of range"))?;
        let token = self.parse(encoded)?;
        let index = token.block_count();
        if index > 8 {
            return Err(TokenError::InvalidInput(
                "attenuation depth cannot exceed 8",
            ));
        }
        let parent = index - 1;
        let code = format!(
            r#"
                tenant{index}({{tenant}});
                model{index}({{model}});
                quota{index}({{budget}});
                max_output{index}({{max_output}});
                expires_unix{index}({{expires}});
                check if tenant{parent}($parent), tenant{index}($child), $parent == $child;
                check if model{parent}($parent), model{index}($child), $parent == $child;
                check if quota{parent}($parent), quota{index}($child), $parent >= $child;
                check if max_output{parent}($parent), max_output{index}($child), $parent >= $child;
                check if expires_unix{parent}($parent), expires_unix{index}($child), $parent >= $child;
                check if request_tenant($requested), tenant{index}($allowed), $requested == $allowed;
                check if request_model($requested), model{index}($allowed), $requested == $allowed;
                check if request_budget($requested), quota{index}($allowed), $requested <= $allowed;
                check if request_output($requested), max_output{index}($allowed), $requested <= $allowed;
                check if request_time($now), expires_unix{index}($expiry), $now < $expiry;
            "#
        );
        let params = HashMap::from([
            ("tenant".to_owned(), builder::string(&narrower.tenant)),
            ("model".to_owned(), builder::string(&narrower.model)),
            (
                "budget".to_owned(),
                builder::int(narrower.budget_microcredits),
            ),
            (
                "max_output".to_owned(),
                builder::int(narrower.max_output_tokens),
            ),
            ("expires".to_owned(), builder::int(expires)),
        ]);
        let block = BlockBuilder::new()
            .scope(Scope::Previous)
            .code_with_params(code, params, HashMap::new())
            .map_err(|_| TokenError::InvalidInput("invalid attenuation"))?;
        let attenuated = token.append(block).map_err(|_| TokenError::InvalidToken)?;
        let encoded = attenuated.to_base64().map_err(|_| TokenError::Internal)?;
        let scope = RequestScope {
            tenant: narrower.tenant.clone(),
            model: narrower.model.clone(),
            requested_budget_microcredits: narrower.budget_microcredits,
            requested_output_tokens: narrower.max_output_tokens,
        };
        self.verify(&encoded, &scope)?;
        Ok(encoded)
    }

    pub fn verify(&self, encoded: &str, scope: &RequestScope) -> Result<(), TokenError> {
        validate_scope(scope)?;
        let digest = token_hash(encoded);
        self.prune_revocations();
        if self
            .revoked
            .lock()
            .map_err(|_| TokenError::Internal)?
            .entries
            .contains_key(&digest)
        {
            return Err(TokenError::Revoked);
        }

        let now = SystemTime::now();
        {
            let mut cache = self.cache.lock().map_err(|_| TokenError::Internal)?;
            prune_cache(&mut cache, now);
            if cache.entries.get(&digest).is_some_and(|entry| {
                entry.scope == *scope && now < entry.expires_at && now < entry.token_expires_at
            }) {
                self.cache_hits.fetch_add(1, Ordering::Relaxed);
                return Ok(());
            }
        }

        let token = self.parse(encoded)?;
        let token_expires_at = token_expiry(&token)?;
        if now >= token_expires_at {
            return Err(TokenError::Unauthorized);
        }
        let now_unix_seconds = i64::try_from(unix_now()?).map_err(|_| TokenError::Internal)?;
        let code = String::from(
            r#"
                request_tenant({tenant});
                request_model({model});
                request_budget({budget});
                request_output({output});
                request_time({now});
                allow if right("om-sanchar", "invoke");
            "#,
        );
        let params = HashMap::from([
            ("tenant".to_owned(), builder::string(&scope.tenant)),
            ("model".to_owned(), builder::string(&scope.model)),
            (
                "budget".to_owned(),
                builder::int(scope.requested_budget_microcredits),
            ),
            (
                "output".to_owned(),
                builder::int(scope.requested_output_tokens),
            ),
            ("now".to_owned(), builder::int(now_unix_seconds)),
        ]);
        let mut authorizer = AuthorizerBuilder::new()
            .code_with_params(code, params, HashMap::new())
            .map_err(|_| TokenError::Internal)?
            .set_limits(authorization_limits())
            .build(&token)
            .map_err(|_| TokenError::InvalidToken)?;
        let authorization_result = authorizer.authorize();
        let authorized = authorization_result.is_ok();

        if !authorized {
            return Err(TokenError::Unauthorized);
        }

        self.prune_revocations();
        if self
            .revoked
            .lock()
            .map_err(|_| TokenError::Internal)?
            .entries
            .contains_key(&digest)
        {
            return Err(TokenError::Revoked);
        }
        self.cache_verified(digest, scope.clone(), now + CACHE_TTL, token_expires_at)?;
        Ok(())
    }

    pub fn revoke(&self, encoded: &str) -> Result<(), TokenError> {
        let token = self.parse(encoded)?;
        let token_expires_at = token_expiry(&token)?;
        if token_expires_at <= SystemTime::now() {
            return Err(TokenError::InvalidToken);
        }
        let digest = token_hash(encoded);
        let mut revoked = self.revoked.lock().map_err(|_| TokenError::Internal)?;
        prune_revocations_locked(&mut revoked, SystemTime::now());
        if !revoked.entries.contains_key(&digest) {
            if revoked.entries.len() >= MAX_REVOKED_ENTRIES {
                return Err(TokenError::RevocationCapacity);
            }
            revoked.expiry_order.insert((token_expires_at, digest), ());
            revoked.entries.insert(digest, RevokedEntry);
        }
        drop(revoked);
        if let Ok(mut cache) = self.cache.lock() {
            cache.entries.remove(&digest);
        }
        Ok(())
    }

    pub fn cache_hits(&self) -> u64 {
        self.cache_hits.load(Ordering::Relaxed)
    }

    pub fn cache_evictions(&self) -> u64 {
        self.cache
            .lock()
            .map(|cache| cache.evictions)
            .unwrap_or_default()
    }

    pub fn revocation_entries(&self) -> usize {
        self.revoked
            .lock()
            .map(|revoked| revoked.entries.len())
            .unwrap_or_default()
    }

    pub fn cache_entries(&self) -> usize {
        self.cache
            .lock()
            .map(|cache| cache.entries.len())
            .unwrap_or_default()
    }

    fn parse(&self, encoded: &str) -> Result<Biscuit, TokenError> {
        Biscuit::from_base64(encoded, self.public).map_err(|_| TokenError::InvalidToken)
    }

    fn cache_verified(
        &self,
        digest: [u8; 32],
        scope: RequestScope,
        expires_at: SystemTime,
        token_expires_at: SystemTime,
    ) -> Result<(), TokenError> {
        let mut cache = self.cache.lock().map_err(|_| TokenError::Internal)?;
        prune_cache(&mut cache, SystemTime::now());
        if let Some(previous) = cache.entries.remove(&digest) {
            cache.expiry_order.remove(&(previous.expires_at, digest));
        } else {
            while cache.entries.len() >= MAX_CACHE_ENTRIES {
                evict_oldest_cache(&mut cache);
            }
            cache.insertion_order.push_back(digest);
        }
        let expires_at = expires_at.min(token_expires_at);
        cache.expiry_order.insert((expires_at, digest), ());
        cache.entries.insert(
            digest,
            CacheEntry {
                scope,
                expires_at,
                token_expires_at,
            },
        );
        Ok(())
    }

    fn prune_revocations(&self) {
        if let Ok(mut revoked) = self.revoked.lock() {
            prune_revocations_locked(&mut revoked, SystemTime::now());
        }
    }
}

fn token_expiry(token: &Biscuit) -> Result<SystemTime, TokenError> {
    let mut authorizer = token.authorizer().map_err(|_| TokenError::InvalidToken)?;
    (0..token.block_count())
        .map(|index| {
            let rule = format!("expiry($value) <- expires_unix{index}($value)");
            authorizer
                .query_all::<_, (i64,), biscuit_auth::error::Token>(rule.as_str())
                .map_err(|_| TokenError::InvalidToken)
                .and_then(|values| {
                    values
                        .into_iter()
                        .map(|value| value.0)
                        .min()
                        .ok_or(TokenError::InvalidToken)
                })
        })
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .min()
        .and_then(|value| u64::try_from(value).ok())
        .and_then(|value| UNIX_EPOCH.checked_add(Duration::from_secs(value)))
        .ok_or(TokenError::InvalidToken)
}

fn authorization_limits() -> AuthorizerLimits {
    AuthorizerLimits {
        max_facts: 4_096,
        max_iterations: 256,
        max_time: Duration::from_millis(250),
    }
}

fn validate_grant(grant: &Grant) -> Result<(), TokenError> {
    if grant.tenant.is_empty() || grant.tenant.len() > 128 {
        return Err(TokenError::InvalidInput("tenant must be 1 to 128 bytes"));
    }
    if grant.model.is_empty() || grant.model.len() > 512 || !grant.model.starts_with("om://") {
        return Err(TokenError::InvalidInput("model must be an om:// address"));
    }
    if grant.budget_microcredits < 0 || grant.max_output_tokens < 0 {
        return Err(TokenError::InvalidInput(
            "grant limits must be non-negative",
        ));
    }
    if grant.expires_at_unix_seconds <= unix_now()? {
        return Err(TokenError::InvalidInput(
            "grant expiry must be in the future",
        ));
    }
    Ok(())
}

fn validate_scope(scope: &RequestScope) -> Result<(), TokenError> {
    if scope.tenant.is_empty() || scope.tenant.len() > 128 {
        return Err(TokenError::InvalidInput("tenant must be 1 to 128 bytes"));
    }
    if scope.model.is_empty() || scope.model.len() > 512 || !scope.model.starts_with("om://") {
        return Err(TokenError::InvalidInput("model must be an om:// address"));
    }
    if scope.requested_budget_microcredits < 0 || scope.requested_output_tokens < 0 {
        return Err(TokenError::InvalidInput(
            "request limits must be non-negative",
        ));
    }
    Ok(())
}

fn token_hash(encoded: &str) -> [u8; 32] {
    Sha256::digest(encoded.as_bytes()).into()
}

fn unix_now() -> Result<u64, TokenError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| TokenError::Internal)
}

fn prune_cache(cache: &mut VerificationCache, now: SystemTime) {
    let mut removed = false;
    while let Some(((expires_at, digest), _)) = cache.expiry_order.first_key_value() {
        if now < *expires_at {
            break;
        }
        let digest = *digest;
        cache.expiry_order.pop_first();
        cache.entries.remove(&digest);
        removed = true;
    }
    if removed {
        let entries = &cache.entries;
        cache
            .insertion_order
            .retain(|digest| entries.contains_key(digest));
    }
}

fn evict_oldest_cache(cache: &mut VerificationCache) {
    if let Some(digest) = cache.insertion_order.pop_front() {
        if let Some(entry) = cache.entries.remove(&digest) {
            cache.expiry_order.remove(&(entry.expires_at, digest));
            cache.evictions += 1;
        }
    }
}

fn prune_revocations_locked(revoked: &mut RevocationList, now: SystemTime) {
    while let Some(((expires_at, digest), _)) = revoked.expiry_order.first_key_value() {
        if now < *expires_at {
            break;
        }
        let digest = *digest;
        revoked.expiry_order.pop_first();
        revoked.entries.remove(&digest);
    }
}

#[cfg(test)]
mod tests {
    use std::time::{Duration, SystemTime, UNIX_EPOCH};

    use super::{Grant, RequestScope, TokenAuthority, TokenError};

    const SECRET: &[u8] = b"om-sanchar-test-root-key-32-bytes!!";

    fn grant(budget: i64, max_output_tokens: i64) -> Grant {
        Grant {
            tenant: "tenant-a".to_owned(),
            model: "om://demo/model/default".to_owned(),
            budget_microcredits: budget,
            max_output_tokens,
            expires_at_unix_seconds: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs()
                + 3_600,
        }
    }

    fn scope(budget: i64, output: i64) -> RequestScope {
        RequestScope {
            tenant: "tenant-a".to_owned(),
            model: "om://demo/model/default".to_owned(),
            requested_budget_microcredits: budget,
            requested_output_tokens: output,
        }
    }

    #[test]
    fn minted_token_verifies_only_for_its_scoped_request() {
        let authority = TokenAuthority::from_secret(SECRET).unwrap();
        let token = authority.mint(&grant(500_000, 64)).unwrap();
        assert!(authority.verify(&token, &scope(100_000, 32)).is_ok());
        assert_eq!(
            authority.verify(
                &token,
                &RequestScope {
                    tenant: "tenant-b".to_owned(),
                    ..scope(100_000, 32)
                }
            ),
            Err(TokenError::Unauthorized)
        );
        assert_eq!(
            authority.verify(
                &token,
                &RequestScope {
                    model: "om://demo/model/other".to_owned(),
                    ..scope(100_000, 32)
                }
            ),
            Err(TokenError::Unauthorized)
        );
        assert_eq!(
            authority.verify(&token, &scope(500_001, 32)),
            Err(TokenError::Unauthorized)
        );
        assert_eq!(
            authority.verify(&token, &scope(100_000, 65)),
            Err(TokenError::Unauthorized)
        );
    }

    #[test]
    fn attenuation_can_only_reduce_the_parent_grant() {
        let authority = TokenAuthority::from_secret(SECRET).unwrap();
        let parent = authority.mint(&grant(500_000, 64)).unwrap();
        let child = authority.attenuate(&parent, &grant(100_000, 32)).unwrap();
        assert!(authority.verify(&child, &scope(100_000, 32)).is_ok());
        assert_eq!(
            authority.verify(&child, &scope(100_001, 32)),
            Err(TokenError::Unauthorized)
        );
        assert_eq!(
            authority.attenuate(&parent, &grant(500_001, 32)),
            Err(TokenError::Unauthorized)
        );
    }

    #[test]
    fn exact_token_revocation_bypasses_a_warm_verification_cache() {
        let authority = TokenAuthority::from_secret(SECRET).unwrap();
        let token = authority.mint(&grant(500_000, 64)).unwrap();
        let request = scope(100_000, 32);
        authority.verify(&token, &request).unwrap();
        authority.verify(&token, &request).unwrap();
        assert_eq!(authority.cache_hits(), 1);
        authority.revoke(&token).unwrap();
        assert_eq!(authority.verify(&token, &request), Err(TokenError::Revoked));
    }

    #[test]
    fn expired_grant_cannot_be_minted() {
        let authority = TokenAuthority::from_secret(SECRET).unwrap();
        let mut expired = grant(100, 10);
        expired.expires_at_unix_seconds = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
            - 1;
        assert_eq!(
            authority.mint(&expired),
            Err(TokenError::InvalidInput(
                "grant expiry must be in the future"
            ))
        );
    }

    #[test]
    fn cache_is_bounded_and_fifo_evictions_are_counted() {
        let authority = TokenAuthority::from_secret(SECRET).unwrap();
        let expires_at = SystemTime::now() + Duration::from_secs(60);
        for index in 0..8_200u64 {
            let mut digest = [0u8; 32];
            digest[..8].copy_from_slice(&index.to_be_bytes());
            authority
                .cache_verified(digest, scope(1, 1), expires_at, expires_at)
                .unwrap();
        }
        assert_eq!(authority.cache_entries(), 8_192);
        assert_eq!(authority.cache_evictions(), 8);
    }

    #[test]
    fn expired_cache_entries_are_removed_on_lookup() {
        let mut cache = super::VerificationCache::default();
        let digest = [3; 32];
        cache.insertion_order.push_back(digest);
        cache.entries.insert(
            digest,
            super::CacheEntry {
                scope: scope(1, 1),
                expires_at: SystemTime::now() - Duration::from_secs(1),
                token_expires_at: SystemTime::now() + Duration::from_secs(60),
            },
        );
        cache
            .expiry_order
            .insert((SystemTime::now() - Duration::from_secs(1), digest), ());
        super::prune_cache(&mut cache, SystemTime::now());
        assert!(cache.entries.is_empty());
    }

    #[test]
    fn revocation_is_retained_until_the_token_expiry() {
        let authority = TokenAuthority::from_secret(SECRET).unwrap();
        let token = authority.mint(&grant(500_000, 64)).unwrap();
        authority.revoke(&token).unwrap();
        assert_eq!(authority.revocation_entries(), 1);
        assert_eq!(
            authority.verify(&token, &scope(1, 1)),
            Err(TokenError::Revoked)
        );
    }
}
