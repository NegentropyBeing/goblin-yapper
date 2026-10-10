# Guia de teste do Goblin Yapper (do zero)

Este guia leva você de um computador sem nada instalado até o Goblin Yapper funcionando, um passo de cada
vez. Não precisa saber programar. Siga os passos na ordem e confira o **"Você deve ver"** de cada um antes de
ir para o próximo. Se algo sair diferente, vá para [Problemas comuns](#problemas-comuns).

Tempo: cerca de 15 minutos, mais o download da voz clonada se você quiser testá-la (opcional).

## O que você precisa

- Um computador com **Windows 10 ou 11** (64 bits) e internet.
- Cerca de **1 GB livre** em disco para o básico.
- Só para a voz clonada (opcional): cerca de **13 GB livres** e, de preferência, uma placa de vídeo **NVIDIA**.
  Sem placa NVIDIA a voz clonada funciona, mas é bem lenta. Dá para testar todo o resto com a voz do Windows.

Você **não** precisa de conta na Twitch, nem do OBS, para fazer o teste básico.

---

## Passo 1: instalar o Python 3.13

O Goblin Yapper é feito em Python, então o Python precisa estar instalado.

1. Abra <https://www.python.org/downloads/windows/> no navegador.
2. Na lista, procure **Python 3.13** e clique em **Windows installer (64-bit)** para baixar.
3. Abra o arquivo baixado.
4. **Importante:** na primeira tela, marque a caixinha **"Add python.exe to PATH"**, lá embaixo.
5. Clique em **Install Now** e espere terminar. Clique em **Close**.

Agora confira se deu certo:

1. Aperte a tecla **Windows**, digite `powershell` e aperte **Enter**. Abre uma janela azul ou preta.
2. Digite (ou copie e cole) o comando abaixo e aperte **Enter**:

   ```powershell
   py -3.13 --version
   ```

**Você deve ver:** `Python 3.13.` seguido de um número, por exemplo `Python 3.13.7`.

Pode fechar essa janela.

---

## Passo 2: baixar o projeto

1. Abra este link no navegador. O download começa sozinho:
   <https://github.com/NegentropyBeing/goblin-yapper/archive/refs/heads/main.zip>
2. Abra a pasta **Downloads**. Clique com o botão direito no arquivo `goblin-yapper-main.zip` e escolha
   **Extrair tudo...**
3. Em "Os arquivos serão extraídos para esta pasta", apague o que estiver escrito e digite `C:\` . Clique em
   **Extrair**.

**Você deve ver:** uma pasta `C:\goblin-yapper-main` com arquivos como `README.md` e `requirements.txt` e
pastas como `goblin_yapper` e `docs`.

Se o Windows não deixar extrair em `C:\`, extraia na pasta **Documentos**. Nesse caso, onde este guia diz
`C:\goblin-yapper-main`, use a pasta `goblin-yapper-main` que ficou dentro de Documentos.

---

## Passo 3: abrir o PowerShell dentro da pasta do projeto

1. Abra a pasta `C:\goblin-yapper-main` no Explorador de Arquivos.
2. Clique na **barra de endereço** no topo da janela (onde aparece o caminho da pasta). O texto fica
   selecionado.
3. Digite `powershell` e aperte **Enter**.

**Você deve ver:** uma janela do PowerShell cuja última linha termina com `C:\goblin-yapper-main>`.

Todos os comandos dos próximos passos são digitados **nessa janela**. Para colar um comando copiado, clique
com o botão direito dentro da janela.

---

## Passo 4: instalar as dependências

São dois comandos. Rode um de cada vez, esperando o primeiro terminar (a linha `C:\goblin-yapper-main>`
volta a aparecer) antes de rodar o segundo.

**Comando 1**, cria um ambiente isolado só para o projeto (uns 20 segundos, não mostra nada na tela):

```powershell
py -3.13 -m venv .venv
```

**Comando 2**, baixa e instala as dependências (até 1 minuto):

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
```

**Você deve ver:** várias linhas de download e, perto do fim, uma linha que começa com
`Successfully installed`. Um aviso `[notice] A new release of pip is available` é normal, pode ignorar.

Não precisa "ativar" o ambiente nem instalar mais nada. Isso só é feito uma vez.

---

## Passo 5: iniciar o Goblin Yapper

Na mesma janela, rode:

```powershell
.venv\Scripts\python -m goblin_yapper
```

**Você deve ver**, em alguns segundos, uma lista de comandos e linhas parecidas com estas:

```
config criado em C:\goblin-yapper-main\config.toml
painel: http://127.0.0.1:8765/panel  |  overlay: http://127.0.0.1:8765/overlay
sem canal da Twitch configurado (use o painel ou: channel <canal>)
>
```

O aviso sobre o canal da Twitch e um aviso `servidor de voz não instalado` são normais nesta etapa.

**Deixe essa janela aberta.** Ela é o programa rodando. Se você fechar a janela, o Goblin Yapper para.

---

## Passo 6: abrir o painel

Abra o navegador (Chrome ou Edge) e entre neste endereço:

<http://127.0.0.1:8765/panel>

**Você deve ver:** uma tela escura com o título **Goblin Yapper**, as abas **Goblin** e **Voz**, uma coluna
**Fila** e colunas coloridas dos times, cada uma com um goblin.

Esse endereço só funciona no seu próprio computador e só enquanto a janela do Passo 5 estiver aberta.

---

## Passo 7: escolher a voz

Clique na aba **Voz**. Escolha **uma** das opções.

### Opção A: voz do Windows (rápida, recomendada para começar)

1. No canto superior direito, em **motor**, escolha **Windows (SAPI)**.

Pronto. O aviso amarelo sobre o servidor de voz pode ser ignorado nesta opção.

### Opção B: voz clonada (OmniVoice)

Só faça se tiver os ~13 GB livres. É demorado na primeira vez.

1. Em **motor**, deixe **OmniVoice (servidor)**.
2. No aviso amarelo, clique em **Instalar servidor de voz**.
3. Espere. A tela mostra o andamento em 5 etapas. São cerca de 3,5 GB de download, de 5 a 20 minutos
   conforme a internet. Não feche nada.
4. Quando terminar, o texto no topo muda para **carregando modelo de voz…** e baixa mais ~3 GB. Espere até
   aparecer **OmniVoice · pronto** com uma bolinha verde.

Para clonar uma voz, você precisa de um arquivo `.wav` com 3 a 20 segundos de fala limpa. **Só use a voz de
alguém com a permissão da pessoa.**

1. Arraste o `.wav` para a área **Arraste um .wav aqui**.
2. Espere as etapas **Preparar áudio** e **Transcrever** ficarem com um ✓ verde. Na primeira vez a
   transcrição baixa mais ~1,6 GB e pode levar alguns minutos; nas seguintes leva segundos.
3. Confira se o texto em **Transcrição** é exatamente o que é dito no áudio. Corrija se precisar.
4. Dê um nome e clique em **Criar perfil**.
5. Em **Voz de cada time**, escolha esse perfil para os times.
6. Em **Testar fala**, clique em **Falar** para ouvir.

---

## Passo 8: roteiro de teste

Volte para a aba **Goblin**. Dá para testar tudo sem a Twitch, adicionando nomes à mão.

**Times**

1. No campo **adicionar nick**, embaixo da coluna **Fila**, digite `ana` e aperte **Enter**. Repita com
   `bia`, `caio` e `duda`. → Os quatro nomes aparecem na Fila.
2. Em **times**, clique em **2**. → Ficam só as colunas Azul e Verde.
3. Clique em **Sortear**. → Dois nomes em cada time, a Fila fica vazia.
4. Arraste um nome de um time para o outro. → O nome muda de coluna.
5. Clique em **Re-sortear**, depois em **Devolver à fila**. → Os times mudam; depois todos voltam para a Fila.
   Clique em **Sortear** de novo para continuar.

**Voz**

6. Em um time, clique em **🔊 Testar voz**. → Você ouve "Fala chat! Aqui é o goblin do time…" e o goblin
   daquele time se mexe enquanto fala. O goblin do outro time fica parado.
7. Clique em **🎤 Sortear voz** no time Azul. → Aparece um cartão com o nome sorteado no topo, e o nome fica
   destacado na coluna.
8. Clique em **⏭ Próximo**. → A voz passa para a outra pessoa do mesmo time.
9. Marque **vários times ao mesmo tempo** e clique em **🎤 Sortear voz** no time Verde. → Dois cartões no
   topo, um de cada time.
10. Clique em **⏹ Parar** no time Azul. → Some só o cartão do Azul. Depois clique em **Parar voz**, no topo.
    → Some o outro cartão e aparece "ninguém com a voz".

**Aparência**

11. Em um time, mude a cor em **tinta** e arraste a barra ao lado. → O goblin daquele time muda de cor na hora.
12. Clique em **Overlay do OBS e imagens do goblin**, lá embaixo, e clique em **copiar** ao lado de
    **Time azul**. Abra uma **nova janela** do navegador (Ctrl+N), cole o endereço e aperte **Enter**. Clique
    uma vez dentro dessa janela (isso libera o som) e deixe-a visível ao lado do painel. No painel, clique em
    **🔊 Testar voz** no Azul. → O goblin da janela nova se mexe e o som sai dela, e no painel aparece uma
    bolinha verde ao lado da URL **Time azul**.

**Com a Twitch (opcional)**

13. No campo **canal da twitch**, digite o nome de um canal e clique em **Conectar**. → Aparece
    `#canal · conectado` com uma bolinha verde.
14. Clique em **Abrir fila** e, no chat desse canal, digite `!joinsort`. → Seu nick aparece na Fila.
15. Passe o mouse sobre o seu nick e clique no 🎤 que aparece ao lado dele. Depois escreva qualquer coisa no
    chat. → A mensagem é lida em voz alta.

---

## Fechar e abrir de novo

- **Para fechar:** na janela do PowerShell, digite `quit` e aperte **Enter** (ou simplesmente feche a janela).
- **Para abrir de novo:** repita só os passos **3**, **5** e **6**. Os passos 1, 2 e 4 são feitos uma única vez.

Suas configurações ficam guardadas na pasta do projeto e voltam quando você abre de novo.

---

## Problemas comuns

| O que aparece | O que fazer |
|---|---|
| `py : O termo 'py' não é reconhecido` | O Python não foi instalado, ou a janela do PowerShell é antiga. Feche a janela, refaça o Passo 1 (marcando **Add python.exe to PATH**) e abra uma janela nova. |
| `Python 3.13 not found` ou `No suitable Python runtime found` | Há outra versão do Python instalada, mas não a 3.13. Instale a 3.13 pelo Passo 1; as duas convivem sem problema. |
| `Não é possível localizar o caminho` ou `requirements.txt` não encontrado | O PowerShell não está na pasta do projeto. Feche-o e refaça o Passo 3. A última linha tem que terminar com `goblin-yapper-main>`. |
| `error while attempting to bind on address ('127.0.0.1', 8765)` | O Goblin Yapper já está aberto em outra janela. Feche a outra janela (ou o app instalado) e rode o Passo 5 de novo. |
| O navegador diz **"Não é possível acessar esse site"** | A janela do Passo 5 foi fechada ou deu erro. Olhe a janela do PowerShell e rode o Passo 5 de novo. |
| `a execução de scripts foi desabilitada neste sistema` | Você tentou "ativar" o ambiente. Não precisa: use os comandos exatamente como estão neste guia. |
| Erro vermelho no Passo 4, comando 2 | Quase sempre é a internet. Confira a conexão e rode o comando de novo. |
| Não sai som | Confira o volume do computador. Na aba **Voz**, veja se o **motor** é **Windows (SAPI)** ou se o topo mostra **OmniVoice · pronto**. Se abriu o overlay em uma aba, clique uma vez dentro dela. |
| A instalação da voz falhou | Clique em **Tentar de novo**. Confira o espaço em disco (~13 GB) e a internet. |
| A tela mostra **"conectando ao servidor…"** | A janela do Passo 5 foi fechada. Rode o Passo 5 de novo; a página volta sozinha. |

## Como avisar de um problema

Mande para quem pediu o teste:

1. O que você fez, passo a passo, e o que esperava que acontecesse.
2. Um print da tela do painel e da janela do PowerShell.
3. O arquivo `goblin-yapper.log`, que fica em `C:\goblin-yapper-main`. Se o problema for de voz clonada,
   mande também `C:\goblin-yapper-main\tts\tts-server.log`.

## Para apagar tudo depois

1. Feche o Goblin Yapper e apague a pasta `C:\goblin-yapper-main`.
2. Se instalou a voz clonada: aperte **Windows + R**, digite `%LOCALAPPDATA%` e aperte **Enter**; apague a
   pasta `GoblinYapper`. Para apagar também o modelo de voz, aperte **Windows + R**, digite
   `%USERPROFILE%\.cache\huggingface` e apague a pasta `hub`. Atenção: essa pasta `hub` também guarda modelos
   de outros programas de IA, se você tiver algum.
3. O Python pode ser removido em **Configurações → Aplicativos**, se você não for usar para mais nada.
