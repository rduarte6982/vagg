// Firefox prefs pra rodar limpo dentro do container saml-portal.
// Aceitar mitmproxy CA (já importado via certutil), sem privacy popups,
// proxy via mitmproxy, sem update prompts, sem hardware accel.
user_pref("network.proxy.type", 1);
user_pref("network.proxy.http", "127.0.0.1");
user_pref("network.proxy.http_port", 8080);
user_pref("network.proxy.ssl", "127.0.0.1");
user_pref("network.proxy.ssl_port", 8080);
user_pref("network.proxy.socks_remote_dns", true);
user_pref("network.proxy.no_proxies_on", "localhost,127.0.0.1");
user_pref("security.enterprise_roots.enabled", true);
user_pref("app.update.enabled", false);
user_pref("app.update.auto", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.tabs.warnOnCloseOtherTabs", false);
user_pref("datareporting.policy.firstRunURL", "");
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("layers.acceleration.disabled", true);
user_pref("dom.ipc.processCount", 1);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("signon.rememberSignons", false);
user_pref("dom.disable_open_during_load", false);
