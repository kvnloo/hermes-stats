// Hermes Stats tab: frames the stats client served by this plugin's API at /api/plugins/stats/.
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;

  // The dashboard loads this file from <base>/dashboard-plugins/[@<profile>/]stats/dist/index.js.
  // The base path and profile in that URL are the ones the framed client must use.
  var src = (document.currentScript && document.currentScript.src) || "";
  var match = /^(.*?)\/dashboard-plugins\/(?:@([^/]+)\/)?stats\//.exec(new URL(src, location.href).pathname);
  var base = match ? match[1] : "";
  var profile = match && match[2] ? decodeURIComponent(match[2]) : "";
  var url = base + "/api/plugins/stats/" + (profile ? "?profile=" + encodeURIComponent(profile) : "");

  function StatsPage() {
    return React.createElement("iframe", {
      src: url,
      title: "Hermes Stats",
      style: {
        display: "block",
        width: "100%",
        height: "calc(100dvh - 7rem)",
        minHeight: "32rem",
        border: 0,
        borderRadius: "var(--radius)",
        background: "transparent",
      },
    });
  }

  window.__HERMES_PLUGINS__.register("stats", StatsPage);
})();
