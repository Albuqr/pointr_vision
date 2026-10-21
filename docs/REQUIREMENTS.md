# Requisitos: Pointr

Texto dos requisitos conforme aprovado pela equipe. A coluna de fase em "Rastreabilidade"
foi acrescentada para o desenvolvimento; o texto dos requisitos não foi alterado.

## Requisitos funcionais

* RF01. Reconhecimento do dispositivo: O sistema deve reconhecer dispositivos Android que atendam às especificações técnicas mínimas definidas para uso. Ao conectar o dispositivo, o sistema deve verificar se ele possui câmera e, caso não possua, notificar o usuário de que uma câmera é necessária para iniciar.
* RF02. Monitoramento da câmera: O sistema deve detectar e alertar o usuário, durante a sessão, sobre problemas de hardware e software que afetem a imagem, como perda de sinal, quadros ausentes e defeitos que comprometam a captura, indicando que o dispositivo precisa ser verificado. (tela)
* RF03. Detecção de pessoas: O sistema deve distinguir pessoas de outros objetos na imagem.
* RF04. Rastreamento e identificação: O sistema deve rastrear cada pessoa detectada e atribuir a ela um ID, diferenciando as pessoas entre si. (tela)
* RF05. Reconhecimento de movimentos: O sistema deve rastrear os movimentos dos atletas durante a prática esportiva, como saltos, corridas e arremessos.
* RF06. Controle de sessão: O sistema deve permitir iniciar e encerrar uma sessão, delimitando o intervalo de coleta de dados.
* RF07. Registro de dados: O sistema deve registrar os dados de rastreamento gerados durante a sessão.
* RF08. Registro local: O sistema deve registrar os dados de cada quadro processado e, quando a gravação estiver ativada, o vídeo da sessão, localmente no dispositivo em que está sendo executado.
* RF09. Gravação sem anotações: O sistema deve oferecer a opção de gravar o vídeo sem as anotações de detecção e rastreamento.
* RF10. Relatório de cobertura: Após o encerramento da sessão, o sistema deve apresentar a cobertura do vídeo analisado. (tela)
* RF11. Relatório de falhas: Após o encerramento da sessão, o sistema deve apresentar uma análise dos problemas ocorridos.
* RF12. Cadastro de jogadores: O sistema deve permitir cadastrar, editar e consultar jogadores com os seguintes dados: ID (gerado pelo sistema), nome, data de nascimento, altura, peso, time, número da camisa e posição. (tela)
* RF13. Cadastro de times: O sistema deve permitir cadastrar, editar e consultar times com os seguintes dados: ID (gerado pelo sistema), nome e treinador. Os jogadores do time são os vinculados a ele no cadastro de jogadores.
* RF14. Cadastro de sessões: O sistema deve associar a cada sessão os seguintes dados: ID (gerado pelo sistema), data, time ou times participantes, horário de início e horário de término. A duração deve ser calculada a partir do início e do término.
* RF15. Sincronização da sessão: Após o registro local, o sistema deve enviar os dados e o vídeo da sessão para o armazenamento central do sistema assim que houver conexão disponível. O envio não deve duplicar sessões já sincronizadas, e os arquivos locais só podem ser removidos após a confirmação de que o envio foi concluído com integridade.
* RF16. Planos de assinatura: O sistema deve oferecer dois planos. No plano básico, apenas os dados e estatísticas das sessões são sincronizados com a nuvem. No plano com vídeo, de valor maior, os vídeos das sessões também são armazenados na nuvem.
* RF17. Acesso ao vídeo por plano: No plano básico, os vídeos gravados devem permanecer armazenados sem acesso para visualização, sendo liberados caso o usuário adquira o plano com vídeo.
* RF18. Configuração global de vídeo: No plano com vídeo, o salvamento dos vídeos na nuvem deve ser uma configuração global da conta, aplicada a todas as sessões.
* RF19. Envio de vídeo: Quando a configuração global de vídeo estiver ativa, o sistema deve enviar o vídeo de cada sessão separadamente dos dados. O vídeo só pode ser considerado sincronizado após o envio completo e a verificação de integridade.
* RF20. Retenção após cancelamento: Quando o usuário deixar o plano com vídeo, os vídeos já armazenados na nuvem devem ser mantidos pelo período de retenção definido.

## Requisitos não funcionais

* RNF01. Câmera mínima: A câmera utilizada deve ter resolução mínima de 10 a 12 MP.
* RNF02. Tempo real: O sistema deve processar o vídeo em tempo real.
* RNF03. Operação independente: O sistema deve funcionar sem depender de vídeos gravados, banco de dados ou acesso a internet.
* RNF04. Armazenamento local: Os vídeos devem ser gravados localmente, no dispositivo em que o sistema está sendo executado.
* RNF05. Formatos de vídeo: O sistema deve suportar vídeos nos formatos MP4 e MOV.
* RN06. O número da camisa deve ser único dentro de um mesmo time.
* RN07. Uma sessão pode envolver um time (treino) ou dois times (jogo).
* RNF08. Idempotência: Reenviar dados ou partes de vídeo já recebidos não deve duplicar registros nem arquivos no servidor.
* RNF09. Persistência da fila de envio: Itens pendentes de sincronização devem sobreviver ao fechamento do aplicativo e à reinicialização do dispositivo.
* RNF10. Retomada de envio: Um envio de vídeo interrompido deve ser retomado a partir da última parte confirmada, sem reiniciar o arquivo inteiro.
* RNF11. Proteção de vídeos bloqueados: Os vídeos do plano básico devem ser armazenados de forma que não possam ser reproduzidos fora do sistema antes da liberação.
* RN12. O período de retenção dos vídeos após o cancelamento do plano com vídeo será definido posteriormente.

## Rastreabilidade (requisito → fase)

| Requisito | Fase | Como é verificado | Observação para implementação |
|---|---|---|---|
| RF01 | 01 (parcial), 13 | abrir fonte, alerta quando não há quadros | Com app de câmera existente, o PC vê uma webcam ou URL; "verificar se possui câmera" só é possível com app próprio (fase 13) |
| RF02 | 01 | perda de sinal, quadros congelados, imagem escura | "hardware quebrado" é tratado pelos sintomas detectáveis |
| RF03 | 02 | detecção de pessoas, classe person | |
| RF04 | 02 | IDs temporários de track | ID é por execução; vínculo com jogador cadastrado na fase 11 |
| RF05 | 12 | estimativa de pose + validação manual | Não deduzir saltos/arremessos de deslocamento de caixa (escopo v2) |
| RF06 | 03 | início/fim de sessão | |
| RF07 | 03 | tracks.csv | |
| RF08 | 03 (dados), 04 (vídeo) | frames.csv, video.mkv (D-042) | Ver conflito C-02 |
| RF09 | 04 | vídeo sem anotações | |
| RF10 | 05 | report.json + tela | |
| RF11 | 05 | report.json + tela | |
| RF12 | 06 | CRUD jogadores | Dados pessoais: ver Q-07 |
| RF13 | 06 | CRUD times | |
| RF14 | 06 | sessão com data, times, início, fim; duração calculada | |
| RF15 | 07, 08, 09 | outbox + API + lane de vídeo | Ver conflito C-01 |
| RF16 | 09 | entitlements no servidor | |
| RF17 | 09 | vídeo bloqueado no plano básico | |
| RF18 | 09 | configuração da conta | |
| RF19 | 09 | upload em partes com sha256 | |
| RF20 | 09 | retenção após downgrade | Período: RN12 |
| RNF01 | 01 | registrado em session.json | Ver Q-01: MP mede foto, não vídeo |
| RNF02 | 02, 03 | FPS e app delay medidos e registrados | Critério numérico após baseline (Q-02) |
| RNF03 | 03 | sessão completa sem rede | |
| RNF04 | 04 | vídeo gravado no notebook | |
| RNF05 | 04 | replay de MP4 e MOV | |
| RN06 | 06 | UNIQUE(team_id, shirt_number) | |
| RN07 | 06 | 1 ou 2 times por sessão | |
| RNF08 | 07, 08, 09 | Idempotency-Key, part sha256 | |
| RNF09 | 08 | outbox em SQLite | |
| RNF10 | 09 | GET de partes recebidas | |
| RNF11 | 09 | vídeo cifrado, chave liberada pelo servidor | Ver Q-05 |
| RN12 | 09 | parâmetro configurável | |

## Conflitos conhecidos no texto (não resolvidos)

- **C-01.** RF15 envia "os dados e o vídeo" para todos; RF16 restringe vídeo na nuvem ao plano
  com vídeo. Implementação segue RF16/RF19 até a equipe ajustar RF15.
- **C-02.** RF08 grava vídeo "quando a gravação estiver ativada"; a decisão da equipe foi que o
  plano básico sempre grava, com acesso bloqueado. Implementação: gravação ligada por padrão,
  configurável; registrar a decisão final em DECISIONS.md.
