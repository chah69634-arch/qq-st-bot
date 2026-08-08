function loadRuntimeConfig() {
  loadFeatureFlags();
  loadProxy();
  loadContextConfig();
  loadLlmParams();
  loadScreenPeekSettings();
  loadMetaMode();
  loadRelaySettings();
  loadStickerConfig();
  _ensurePronounUidOptions().then(() => {
    if (document.getElementById('pn-uid-select')?.value) loadUserPronoun();
  });
}
