function loadRuntimeConfig() {
  loadFeatureFlags();
  loadEventShadowRecallSettings();
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
