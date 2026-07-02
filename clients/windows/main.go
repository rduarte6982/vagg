// Package main — entrypoint do VAGG Client (Windows GUI).
//
// O binário GUI é o que o usuário enxerga: tray icon + janela de login +
// dashboard. NÃO faz route add/delete diretamente (isso é problema do
// service `vagg-client-svc`, que roda como SYSTEM). A GUI conversa com o
// service via named pipe local `\\.\pipe\vagg-client`.
package main

import (
	"embed"
	"log"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	app := NewApp()

	// Tray sobe primeiro, em goroutine (systray.Run bloqueia). O ícone aparece
	// imediatamente e os handlers (show/quit) são preenchidos quando o Wails
	// terminar de subir e tivermos o ctx. Assim o usuário sempre vê o tray,
	// mesmo se o Wails demorar pra abrir a janela.
	go runTray()

	err := wails.Run(&options.App{
		Title:             "vagg client",
		Width:             520,
		Height:            720,
		MinWidth:          440,
		MinHeight:         600,
		HideWindowOnClose: true, // X minimiza pro tray (não fecha o processo)
		// SingleInstanceLock: re-abrir o atalho/.exe traz a janela existente.
		SingleInstanceLock: &options.SingleInstanceLock{
			UniqueId: "vagg-client-39a7c810",
			OnSecondInstanceLaunch: func(_ options.SecondInstanceData) {
				if h := snapshotHandlers(); h.show != nil {
					h.show()
				}
			},
		},
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		// Background da janela = vagg deep ink (#0b0d10) — mesmo da paleta brand.
		BackgroundColour: &options.RGBA{R: 11, G: 13, B: 16, A: 255},
		OnStartup:        app.startup,
		OnShutdown:       app.shutdown,
		Bind: []interface{}{
			app,
		},
		Windows: &windows.Options{
			WebviewIsTransparent: false,
			DisableWindowIcon:    false,
		},
	})

	if err != nil {
		log.Fatalf("vagg-client failed to start: %v", err)
	}
	// Garante que o systray também encerra quando o Wails sai.
	stopTray()
}
