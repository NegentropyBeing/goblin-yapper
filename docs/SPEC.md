# Frontend and Script Process. 


## Predicates:

* Purpose: to create an integrated app/service that will encompass: team sorter + gif react "avatar" + TTS.
* Rust or Python?
* The script shall be worked first and later will produce frontend app.


### Team sort

* The chat feed will be received using the anonymous chat reader "twitch-irc" and from the script we will detect commands, like !joinsort. 
* The user set the number of teams, up to 4 (all portuguese color names "azul", "verde", "Roxo", "Amarelo"). 
  * The number of teams shall be determined in the app/script before or after we turn the queue on. 
* The idea is to  create an algorithm to sort teams, from a simple chat comand like !joinsorting in a twitch channel. People will first join a queue and then, will be sorted. 
  * Some people might join the queeu  later, and in that case they should be sorting 
  * It should be possible to allow the app operator/user to change chatters from team. Dependending of the front end tool we develop, a drag and pull should be possible for the rearrenge.
  * There should also be an option to clean all the teams, and option to give everyone back to the queue and another option to resort teams. 
* that will show the list of nicknames (chatters) in each team.  
* Need to define ruleset for the TTS activation:  
  * "três ou quatro times são divididos entre as pessoas que dão !joinsorting -> eu aperto um botão pra dar voz a alguém aleatório em um time  -> as mensagens dessa pessoa são lidas pelo tts enquanto ela estiver ativa -> posso parar apertando em outro botão -> eu aperto o botão novamente e o bot sorteia outra pessoa do mesmo time... ou eu aperto um botãoo e sorteia-se alguém do time azul"
  * Seria importante adicionar uma forma de selecionar alguém em específico para receber a voz


### Goblin yapper

* Gif react to "text to speech" from chat, moving only when the responsible chatter or team text their message.
* two states: 

  * not speaking: frozen png
  * speaking: active gif
* Each team, a goblin gif. Maybe there should be a color tint filter applied over the image (customizable through front end option).
* Local AI voice model will be loaded at the GPU level, ready to replicate the content from the sorted chatter. 
* This will result in an artifact to be used by OBS (don't really know what... maybe a web). 

### Omnivoice TTS

* TTS will reproduce what chat is speaking, from the Omnivoice Model, to couple with the "goblin_yapper" process
* Cloning voices should be usable as per the script (working on it currently)
