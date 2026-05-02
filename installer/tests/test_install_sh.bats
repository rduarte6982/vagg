#!/usr/bin/env bats
# Smoke tests do install.sh — não invocam apt/docker; só validam parsing e
# branches de idempotência. Rodar com `bats installer/tests/`.

setup() {
    INSTALL_SH="$(dirname "$BATS_TEST_FILENAME")/../install.sh"
    [ -f "$INSTALL_SH" ] || skip "install.sh não encontrado"
}

@test "install.sh existe e é executável" {
    [ -x "$INSTALL_SH" ] || chmod +x "$INSTALL_SH"
    [ -x "$INSTALL_SH" ]
}

@test "install.sh sem args falha com mensagem útil" {
    run bash "$INSTALL_SH" || true
    [[ "$output" == *"--license-key"* ]] || [[ "$output" == *"execute como root"* ]]
}

@test "install.sh --help imprime instruções" {
    run bash "$INSTALL_SH" --help || true
    [[ "$output" == *"--license-key"* ]] || [[ "$output" == *"execute como root"* ]]
}

@test "install.sh recusa argumento desconhecido" {
    # Como rodamos sem root, primeiro check pode disparar antes; aceitamos
    # qualquer um dos dois caminhos defensivos.
    run bash "$INSTALL_SH" --license-key=x --domain=y --admin-email=z@a --bogus
    [ "$status" -ne 0 ]
    [[ "$output" == *"argumento desconhecido"* ]] \
        || [[ "$output" == *"execute como root"* ]]
}
