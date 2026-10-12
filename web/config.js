// Local defaults. deploy.sh generates the real file (with your API URL) at deploy time and
// uploads that copy to the storage static website, so this one is never edited in place.
window.APP_CONFIG = {
  apiBaseUrl: "",          // for example https://apim-xyz.azure-api.net/docint
  defaultModel: "prebuilt-invoice",
  maxUploadMb: 20,
  reviewThreshold: 0.8     // fields below this confidence are flagged "Review"
};
