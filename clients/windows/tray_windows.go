// tray_windows.go — ícone na bandeja do Windows (ao lado do relógio).
//
// Inicia em paralelo com o Wails, em uma goroutine. Quando o usuário clica X
// na janela do app, ela é escondida (HideWindowOnClose) e o ícone do tray é
// a única forma visível de trazê-la de volta — exatamente como Slack/Teams.
//
// Os handlers que mexem com a janela (show / quit) só ficam disponíveis depois
// que o Wails subiu (precisa do ctx). Antes disso, cliques no menu são no-op.
//
//go:build windows

package main

import (
	_ "embed"
	"sync"

	"github.com/getlantern/systray"
)

//go:embed build/icon.ico
var trayIconData []byte

type trayHandlers struct {
	show func()
	quit func()
}

var (
	trayMu       sync.RWMutex
	trayCurrent  trayHandlers
	trayQuitOnce sync.Once
)

// runTray sobe o systray. Bloqueia até systray.Quit ser chamado.
// Por isso é iniciado em goroutine pelo main().
func runTray() {
	systray.Run(onTrayReady, func() {})
}

// stopTray desliga o systray (chamado no shutdown do Wails). Idempotente.
func stopTray() {
	trayQuitOnce.Do(func() {
		systray.Quit()
	})
}

func registerTrayHandlers(show, quit func()) {
	trayMu.Lock()
	trayCurrent = trayHandlers{show: show, quit: quit}
	trayMu.Unlock()
}

func snapshotHandlers() trayHandlers {
	trayMu.RLock()
	defer trayMu.RUnlock()
	return trayCurrent
}

func onTrayReady() {
	if len(trayIconData) > 0 {
		systray.SetIcon(trayIconData)
	}
	systray.SetTitle("vagg.")
	systray.SetTooltip("vagg client — clique pra abrir")

	mShow := systray.AddMenuItem("Mostrar vagg client", "Trazer a janela")
	systray.AddSeparator()
	mQuit := systray.AddMenuItem("Sair", "Encerrar vagg client")

	go func() {
		for {
			select {
			case <-mShow.ClickedCh:
				if h := snapshotHandlers(); h.show != nil {
					h.show()
				}
			case <-mQuit.ClickedCh:
				if h := snapshotHandlers(); h.quit != nil {
					h.quit()
				}
				stopTray()
				return
			}
		}
	}()
}
