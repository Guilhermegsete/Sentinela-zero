# SENTINELA ZERO — V0.4.1 Visual

Piloto público de monitoramento solar e noticiário. Python 3.12, biblioteca padrão, sem credenciais. Infraestrutura prevista: GitHub Pages e Actions, sem contratar serviços adicionais.

## Componentes e fontes

- `docs/index.html`: apresentação; `docs/dashboard.js`: gráficos, atualização e estados.
- `scripts/collect.py`: NOAA SWPC (Kp estimado, regiões, flares e boletins), NASA SDO e RSS BBC World/Al Jazeera.
- NASA AIA 193: `https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0193.jpg`; metadado: `times0193.txt` no mesmo diretório.
- NASA HMI intensidade contínua: `latest_512_HMII.jpg`; metadado: `hmitimes.txt`. Não é magnetograma.
- Schumann: referências externas GCMS/HeartMath, sem telemetria numérica integrada.
- `docs/data.json`: snapshot e diagnóstico por fonte. O histórico Git preserva versões anteriores.

## Integridade, horários e retenção

Horários NOAA sem sufixo são interpretados como UTC e normalizados com fuso explícito. Horários textuais no painel usam Brasília (BRT); barras diárias de flares usam dias UTC.

Kp precisa ser numérico, finito e entre 0 e 9; ausência não vira zero. Registros incompatíveis e datas mais de cinco minutos no futuro são rejeitados. A pequena tolerância é para desvio de relógio; o gráfico só usa observações até o instante atual.

O coletor combina Kp anterior e atual, deduplica por horário (a resposta nova prevalece) e retém 24 horas sem corte fixo de 720 amostras. A tela informa o intervalo entre primeira e última leitura e as lacunas maiores que dois minutos; a linha é interrompida nas lacunas. Intervalo coberto não equivale a cobertura contínua. Amostras ausentes não são inventadas; não é possível recuperar retroativamente dados que nunca foram coletados.

O histórico de flares mantém a resposta do endpoint de sete dias sem corte de 250 eventos. Lista vazia válida significa nenhum evento reportado. Falha e ausência de dados são estados diferentes; idade do último evento não é idade da fonte. Dias posteriores à última consulta ficam sem cobertura, e não como zero.

Limites de atualidade:
- consulta por fonte: 45 minutos;
- observação Kp: 45 minutos;
- regiões: 48 horas;
- metadado de observação NASA: duas horas.

Em falha, a entrada anterior é retida com os horários originais e `stale: true`. O snapshot é gravado atomicamente antes de o processo terminar com código 1 por qualquer fonte antiga ou falha. O diagnóstico não renova a data de uma observação ou consulta anterior.

O horário do metadado NASA não comprova que o JPG recebido pelo navegador corresponde à mesma captura; conferir o rodapé da imagem.

## Coleta, atualização e recuperação

O cron solicita coleta aos minutos 7, 22, 37 e 52 de cada hora UTC. GitHub pode atrasar ou descartar agendamentos. Não há garantia de pontualidade ou monitoramento contínuo.

O navegador consulta snapshot e imagens a cada cinco minutos enquanto visível, recalcula a idade a cada 30 segundos e atualiza ao voltar do segundo plano. O botão manual recarrega dados publicados; não executa o coletor.

O workflow salva o diagnóstico mesmo após coleta degradada e depois reporta a falha. Só salva snapshots em `main`. Um push concorrente rejeitado exige reconciliar o estado e executar novamente sobre a versão atual; não forçar ou sobrescrever.

Para investigar:
1. Comparar execuções por `schedule` com horários esperados.
2. Conferir `generated_at`, `fetched_at`, `observed_at`, `health` e `status`.
3. Separar falha de coleta, de gravação e de Pages.
4. Se o job não iniciar ou for interrompido antes de salvar, o snapshot anterior permanece; o navegador sinaliza seu envelhecimento.

Não há alerta externo ou processo permanente criado por estas alterações. A causa dos intervalos longos observados na auditoria continua pendente; o código não elimina as limitações do agendamento GitHub.

## Testes e verificação

Python 3.12 e Node.js 22 ou superior:

```sh
python -m py_compile scripts/collect.py
python -m unittest discover -s tests -v
node --check docs/dashboard.js
node --test tests/test_dashboard.cjs
```

Testes offline cobrem validação, UTC, retenção, deduplicação, lacunas, falhas parciais/totais, gravação do diagnóstico, respostas vazias, temporizadores, segundo plano e falhas de atualização. O painel é testado também em outro fuso.

A validação roda em pushes para `main`, `codex/**`, a branch histórica V0.4 e em pull requests para `main`; não publica o site.

Após eventual implantação, verificar uma janela de 24 horas: coletas esperadas/realizadas, atrasos, aumento real da cobertura Kp e estados por fonte. Esta observação é recomendada; não está configurada como automação permanente.

## Publicação e revisão

Pages usa `main`, pasta `/docs`. Uma branch de revisão não modifica essa publicação. Incorporar alterações à `main` é decisão separada: esse push pode disparar coleta e publicação. O coletor de produção não deve ser executado na branch de revisão.

O snapshot da branch é herdado da base; os testes não fabricam observações atuais. A V0.4.1 lê o snapshot anterior e sinaliza metadados ausentes até uma coleta com a nova versão.

## Limites

Visualização informativa, sem uso como alerta crítico. O Kp é estimativa NOAA atualizada por minuto, não uma medição independente. Boletins listados não são necessariamente ativos. Manchetes são conteúdo de terceiros. Fontes podem mudar de esquema ou ficar indisponíveis. Repositório e dados publicados são públicos.

