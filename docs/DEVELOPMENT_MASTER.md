# OpenTrace BIM — Registro mestre de desenvolvimento

**Referência:** 2026-10-09 · **Repositório:** `lelopes05/opentrace-bim` · **Release preservado:** 0.12.9

> Abrir a próxima conversa lendo este arquivo na branch/PR de desenvolvimento mais recente. Validar commits/arquivos reais antes de declarar algo integrado. Atualizar este registro ao fechar cada bloco.

## Ponto de retomada prioritário — 2026-10-10

**Trabalho ativo:** [PR #8](https://github.com/lelopes05/opentrace-bim/pull/8), branch `dev/opening-controller-integration-2026-10-10`, base `dev/wall-openings-2026-10-09` (PR #5). Integra a implementação independente de esquadrias do [PR #7](https://github.com/lelopes05/opentrace-bim/pull/7). PRs #3–#7 seguem abertos e sem merge na `main`. **Release público 0.12.9 e catálogo preservados.**

**Regra atual:** a implementação foi autorizada; evolução/correções devem ficar na branch experimental até prova visual no IngeTrazo e avaliação do usuário. O código possui testes Python/host reais, mas os sintomas observados em renderização **somente com seleção ativa** NÃO podem ser declarados corrigidos sem reprodução visual. Manter a distinção entre teste headless e GUI.

## Regras permanentes

- Responder às perguntas do usuário ANTES de programar. Ele valida comportamento e interface; revisão de arquitetura e código é responsabilidade técnica do assistente.
- Trabalhar em blocos e avançar com frentes independentes enquanto o usuário testa outras. Evitar alterações simultâneas ao mesmo arquivo; reconciliar antes de juntar.
- Não empacotar, instalar, mesclar na `main`, publicar release ou atualizar catálogo sem autorização. Branch de desenvolvimento + PR rascunho permitidos.
- Distinguir testes Python de execução do plugin dentro do IngeTrazo. Não alegar teste de runtime não executado.
- Patches de conversas anteriores NÃO equivalem a commits no GitHub. Conferir arquivos e reaplicar conforme necessário.

## Contratos e limites entre motores

- Geometria única paramétrica: `model.py` (parede), `slab_model.py` (laje), `column_model.py`, `beam_model.py`; metadados IFC em `bim.py`, camadas em `layers.py`.
- `levels.py` lê dados da extensão Niveles sem tomar posse do namespace. Reutilizar cenas, cortes, escala e Compositor do IngeTrazo, com APIs privadas centralizadas no adaptador `host.py` quando necessário.
- `architecture_contracts.py` é apenas um contrato JSON-safe de vistas, aberturas e hachuras; não executa ações e não deve alterar o comportamento da 0.12.9.
- Uma vista salva contém câmera, corte, nível, escala de representação e tipo de representação. Nunca duplicar a geometria do modelo.
- A escala 1:50 rege símbolos, hachuras e tamanho gráfico das cotas; NÃO trava o zoom nem promete escala física do monitor.
- 3D livre, inclusive com seção temporária: representação `simple`, sem trama. Planta, corte e elevação documentados: `architectural`. Isométrica cortada pode optar pelo modo arquitetônico.
- Criar cenas/cortes por comandos undoáveis; não modificar `scene.saved_views` ou `scene.section_planes` diretamente sem história (IngeTrazo issue #310).
- Abertura é geometria do hospedeiro; porta/janela é objeto de preenchimento separado e associado por `source_id`. Aberturas livres não exigem elemento de preenchimento.
- Parede deve aceitar abertura livre poligonal (vértices/arestas) em coordenadas locais (distância ao longo do caminho, altura), inclusive curva; retângulos legados mantêm `position,width,sill,height`.
- Permitir `sill=0` nas portas; **não apagar parede baixa** quando porta nominal for mais alta. Recriar malha sem arestas fantasmas. Preservar GUID e abertura/objeto após edição e salvar/reabrir.
- Mínimo: uma porta de abrir e uma janela paramétricas. Porta: três pontos de ancoragem (esquerda/centro/direita), botão único para inverter giro, hotspots/paleta radial; altura só no hotspot superior, posição só nos inferiores, largura em todos.
- Ferragens, puxadores, dobradiças e armaduras complexas são futuros plugins conectáveis; terreno avançado adiado.
- Tramas são vetoriais, editáveis e paramétricas, associadas a materiais/camadas, escalas `paper` (mm de folha) e `model` (m reais); cache por geometria/corte/material/escala, e só renderizam em vistas arquitetônicas.
- Paleta lateral conserva edição. Nova barra contextual é só para criação. Informações do Projeto têm botão próprio mas usam o cadastro BIM existente, acrescido de cliente/localização.
- Manual `?` contextual começa com `O que há de novo` em cada release. Sobre inclui GitHub, discussão IngeTrazo #449 e atualizador oficial; nenhum site fictício.
- Alinhamento/distribuição X/Y/Z em paleta ancorável, com limites reais de grupos e histórico undoável do host.

## Etapas — ordem REAL de desenvolvimento (reordenadas em 2026-10-09)

**A numeração abaixo é a ordem de prioridade e de dependência para execução — substitui os antigos números de blocos na seção de planejamento.** Os números dos PRs GitHub são identificadores permanentes e NÃO acompanham essa renumeração. O 05A antigo = etapa **01** atual; o 05B antigo = etapa **02** atual.

| Etapa atual | Escopo | Estado verificado / referência histórica |
|---|---|---|
| 00 | Fundação técnica, contratos e testes | Preparada no PR #3; ainda não mesclada na main |
| **01** | **Aberturas de paredes:** retângulos no piso/topo, abertura livre poligonal, edição por vértices/arestas, paredes curvas e malha sem arestas indevidas | **Código experimental + UI inicial no PR #5.** Testes puros/compilação passam em CI; avaliação de runtime, malha e cortes pendente |
| **02** | **Portas e janelas paramétricas:** objetos de preenchimento, uma porta de abrir e uma janela, âncoras esquerda/centro/direita, inversão de giro, hotspots/paleta radial, IFC | **Próxima prioridade, depende da 01.** Antigo bloco 05B; não implementado |
| 03 | Integração de criação/edição de aberturas, portas e janelas à paleta | Pendente; depende da geometria e dos objetos das etapas 01–02 |
| 04 | Interface geral: barra de criação, menus, Informações do Projeto, manual, Sobre, alinhamento/distribuição X/Y/Z | Parcial em PRs #4 e #6, ambos não mesclados; podem evoluir em paralelo sem conflitar com 01 |
| 05 | Vistas arquitetônicas: cenas, plantas por pavimento, cortes, elevações, escalas | Barra em patch anterior; cenas automáticas pendentes |
| 06 | Representação 2D: cotas, símbolos e tramas vetoriais paramétricas por material/camada e escala | Contrato preparado, renderizador/editor pendentes |
| 07 | Compositor, consolidação IFC, interoperabilidade, round-trip e testes finais | Integração transversal e validação final pendentes |

**Ordem prioritária de execução:** 00 (fundação de suporte) → **01 aberturas** → **02 portas e janelas** → 03 integração à paleta → 04 interface geral → 05 vistas → 06 representação 2D/tramas → 07 Compositor/IFC/consolidação. Partes independentes das etapas 04 e 05 podem ser preparadas paralelamente. IFC e testes básicos ocorrem desde o início, embora a consolidação final seja 07.

**Mapa de números antigos (somente para leitura de commits e PRs):** 00 → 00; antigo 05A → novo 01; antigo 05B → novo 02; parte da antiga 01 → novo 03 (integração à paleta); antigas 01 e 02 → novo 04 (interface/alinhamento); antiga 03 → novo 05; antigas 04 e 06 → novo 06; antiga 07 → novo 07. O registro histórico abaixo ainda pode mencionar 05A/05B ao citar o código/PR de sua época.

## Achados concretos da versão 0.12.9

- `model.py::normalize_wall_openings()` aceita apenas retângulos internos com margem em cima e embaixo, e impede portas no piso. Precisamos substituir esse limite e resolver as arestas que sobram.
- `openings.py::host_capabilities()` declara `embedded_polygon=False` em paredes. Não declarar suporte antecipadamente sem gerador funcional.
- `slab_opening.py` / `slab_opening_edit.py` já têm o padrão de UX para polígonos. Não transplantar sem adaptar a geometria local da parede.
- `bim.py` já salva projeto/terreno/edifício/autor/organização. Cliente e localização devem entrar no mesmo registro, sem dados duplicados.
- `levels.py` consulta Niveles; proposta de plantas por nível foi registrada no issue #310 do IngeTrazo, mas o código público de Niveles consultado ainda não possuía geração automática.
- IngeTrazo já tem cenas com cortes, Compositor com escala real e uma hachura vetorial 45°; falta biblioteca de material por escala na viewport.
- Arquivo local de conversas anteriores: `opentrace_ui_pending_cumulative.patch` contém barra de vistas, manual/Sobre e alinhamento, mas só valerá como implementado após integração e teste.

## Execução e handoff — sequência atual

1. **Etapa 00:** preservar e validar os contratos e os testes da fundação do PR #3.
2. **Etapa 01 (antiga 05A; PR #5):** concluir o motor de aberturas retangulares e poligonais; validar geometria de paredes baixas, inclinadas, curvas, multicamadas, junções e IFC; eliminar faces/arestas residuais; disponibilizar desenho/edição por vértices/arestas; testar no IngeTrazo, Undo/Redo e salvar/reabrir `.igz`.
3. **Etapa 02 (antiga 05B):** implementar porta de giro e janela como objetos paramétricos separados dos vazios; associar por `source_id`; respeitar âncoras e hotspots definidos; validar IFC.
4. **Etapa 03:** ligar criação e edição desses elementos às paletas e menus contextuais sem antecipar suporte não validado.
5. **Etapa 04:** reconciliar UI e cadastros do PR #4, alinhamento/distribuição do PR #6, manual e Sobre; validar caixas, seleção, Undo/Redo e persistência. Trabalho sem conflito pode avançar em paralelo.
6. **Etapas 05–06:** cenas, vistas, cortes, escalas, cotas, símbolos e tramas vetoriais. Reusar o host e o Compositor sem duplicar geometria.
7. **Etapa 07:** consolidar IFC, Compositor, round-trip e regressões (Bonsai, Archicad, FreeCAD conforme ambientes disponíveis); não confundir testes Python com teste de runtime.
8. Antes de encerrar cada conversa, registrar status **verificado**, arquivos, testes realmente executados, branch/commit, pendências e próxima ação.

**Prompt de retomada:** Leia `docs/DEVELOPMENT_MASTER.md` na branch mais recente de `lelopes05/opentrace-bim` e os PRs #3–#6; preserve a **ordem atual 01 aberturas → 02 portas/janelas → 03 paletas**, sem usar a numeração histórica 05A/05B como prioridade. Mantenha o documento atualizado. Não empacote, mescle na `main`, instale ou publique release/catálogo sem autorização.

## Atualização da frente 05A — 2026-10-09

- Branch `dev/wall-openings-2026-10-09`, independente da branch 01. `opening_profile.py` (planejamento numérico com teste) e `model.py` (primeira alteração experimental do gerador de vãos retangulares), `tests/test_opening_profile.py`.
- **Validado localmente:** 6 testes puros de cortes com porta no piso, porta mais alta que parede, janela normal, janela sem interseção, topo inclinado e ausência de cruzamento; juntamente com os 10 testes de contratos, 16 testes passaram no ambiente de preparação.
- **Ainda NÃO validado:** execução da malha `model.py` no IngeTrazo, verificação visual das faces/arestas, paredes curvas e inclinadas, junções, composições multicamadas, IFC e salvar/reabrir `.igz`.
- **Ainda NÃO implementado:** aberturas livres poligonais editáveis por vértices/arestas em paredes, porta de giro e janela paramétrica. Não anunciar a nova capacidade no painel até validação e teste.
- Antes de mesclar, revisar a geometria com o IngeTrazo e testar se o contorno fica totalmente limpo inclusive em vistas com corte.

## Atualização 05A — retomada e geometria poligonal (2026-10-09)

- **Branch de trabalho:** `dev/wall-openings-2026-10-09` (PR #5; base PR #3). PRs #4 (UI) e #6 (alinhar/distribuir) continuam separados, abertos e não mesclados. Release público e catálogo `0.12.9` não foram alterados.
- **Commits desta retomada:** `eb246f3` (geometria poligonal pura), `4dc93e8` (9 testes de regressão planejados), `37b06c7` (integração experimental da malha ao `model.py`), `0008450` (validação de interseção pelo perfil inclinado real). Arquivos: `OpenTrace_BIM/wall_polygon.py`, `tests/test_wall_polygon.py`, `OpenTrace_BIM/model.py`.
- **Implementado em código, não habilitado pela UI:** normalização básica de abertura poligonal na parede (coordenadas locais distância/altura); conservação de `id`, `source_id`, `ifc_global_id`; particionamento das faixas pela silhueta da abertura e pelo perfil de altura da parede; tentativa de gerar superfícies de requadro por aresta; despacho para gerador poligonal somente quando o registro contém abertura dessa classe. Retângulos legados continuam no caminho antigo.
- **A validar/corrigir ANTES de apresentar ao usuário:** executar testes Python (os 9 casos novos ainda não foram executados nesta retomada); confrontar faces e arestas de malha reais no IngeTrazo; concavidade, cruzamentos, curvas, paredes inclinadas/multicamadas, junções, Undo/Redo, salvar/reabrir `.igz`, e exportação IFC. Ainda falta a ferramenta de desenho e edição por hotspots na UI; `host_capabilities` mantém `embedded_polygon=False` até confirmação.
- **Sem promessa de funcionalidade concluída:** portas e janelas paramétricas são o bloco 05B, ainda não iniciado na interface. Não criar release/instalador nem mesclar a `main` sem autorização.
- **Próximas ações técnicas:** (1) testar e corrigir o algoritmo poligonal, inclusive arestas coincidentes com piso/topo e contorno limpo; (2) editor de abertura livre e edição de vértices/arestas análogos aos da laje; (3) teste de runtime do bloco 05A; (4) porta de giro e janela paramétricas com objeto independente preenchendo abertura, âncoras esquerda/centro/direita, inversão de giro e hotspots conforme contrato; (5) IFC e testes de persistência.
- **Nota de histórico:** os testes `16 passaram` anotados anteriormente pertencem à preparação do PR #5, não representam novos testes executados nesta retomada.

## Retificação de prioridade e numeração — 2026-10-09

- A numeração histórica 05A/05B deixou de representar a ordem de execução. **Ordem vigente: 01 aberturas → 02 portas/janelas → 03 integração às paletas → 04 interface geral → 05 vistas → 06 representação 2D/tramas → 07 Compositor/IFC e consolidação.** A fundação é etapa 00.
- PRs não foram renumerados nem mesclados; o PR #5 ainda reúne a frente de aberturas e o PR #3 mantém a base contratual. Os nomes antigos só ficam para rastreabilidade dos commits anteriores.
- Esta atualização altera somente o documento mestre na branch experimental de aberturas; nenhuma mudança no release 0.12.9 ou no catálogo.

## Retomada ativa — Etapa 01 (2026-10-09)

- **Desenvolvimento efetivo no PR #5**, branch `dev/wall-openings-2026-10-09`, sem alterar main, release público 0.12.9 ou catálogo.
- **Ferramenta nova:** `OpenTrace_BIM/wall_polygon_tool.py` (commit `d7868f8`) desenha abertura poligonal com cliques e fechamento no primeiro vértice. Projeta os pontos no sistema local distância/altura de parede reta ou curva. Só confirma com `EditWall` e o histórico do host; cancelar não altera a parede.
- **Conexão à interface:** `host.py` (`82b63fe`); `ui.py` (`0828686` e `bea750c`), com botão `⬡` na paleta contextual da parede e controles específicos na paleta lateral para mover/inserir/excluir vértices e mover arestas. Campos de retângulos ficam ocultos para não sobrescrever polígonos.
- **Operações geométricas novas:** `wall_polygon.py` (`82e76f1`): `insert_vertex`, `move_vertex`, `move_edge`, `delete_vertex`, revalidadas contra degeneração e auto-interseção. Gesto interativo em `wall_polygon_tool.py` (`6397172`); testes adicionais em `tests/test_wall_polygon.py` (`31c4de2`).
- **Validação automática real nesta retomada:** workflow `.github/workflows/test-wall-openings.yml` (commit `3b0d62a`) criado para rodar `python -m unittest discover -s tests -v` e `python -m compileall -q OpenTrace_BIM`. GitHub Actions [run 37974548958](https://github.com/lelopes05/opentrace-bim/actions/runs/37974548958), head `31c4de2`, **success**: etapa de testes unitários passou e compilação de módulos Python passou. São 29 testes definidos (10 contratos + 6 perfis + 13 poligonais); essa validação NÃO carrega PySide6, host nem malha real.
- **Estado correto:** código de criação e edição da abertura livre existe na branch, mas **NÃO validado no IngeTrazo**; não anunciar como concluído. Pendências: confirmar projeção na parede curva pela viewport real, contornos e faces sem arestas indesejadas (incluindo inclinadas, multicamadas e junções), seleção/UX, Undo/Redo, salvar/reabrir `.igz`, IFC com aberturas e compatibilidade de obras antigas. Editor de arcos/chanfro/fillet da abertura livre também não está concluído.
- **Próximo gate:** conferir a operação 01 visualmente no IngeTrazo após corrigir eventuais falhas de runtime; em seguida iniciar **Etapa 02: porta de abrir + janela paramétrica** com `source_id` e hotspots sem confundir modelo paramétrico com mera classificação IFC.

## Fechamento do checkpoint de código — Etapa 01 (2026-10-09)

- **Últimas verificações**: commits `36de355` e `06b9249` endurecem o validador contra arestas inferiores a 1 mm e retorno collinear de vértices, com duas novas regressões.
- **CI confirmada, não apenas presumida:** GitHub Actions [run 37974788083](https://github.com/lelopes05/opentrace-bim/actions/runs/37974788083) na branch de aberturas, SHA `06b9249`: conclusão `success`. Log do job `113970216585` relata **Ran 31 tests ... OK**, e etapa separada `python -m compileall -q OpenTrace_BIM` `success`.
- **Não confundir com funcionamento no host:** não houve execução do plugin no IngeTrazo nesta conversa, portanto a UI nova e os recortes de malha ainda são experimentais e o PR #5 continua rascunho.
- **Próxima ação:** validação de runtime com paredes retas/curvas, portas no piso, abertura poligonal concava e inclinada, multicamadas, Undo/Redo, salvar/reabrir, contorno sem linhas fantasmas; corrigir resultados antes de liberar a etapa 02.

## Execução autorizada — continuidade 01 e 02 (2026-10-09)

**Decisão do mantenedor:** seguir desenvolvendo sem aguardar aprovação a cada subetapa, preparar pacote de teste da 01 e evoluir base técnica da 02 em branch independente; não mesclar na `main` nem publicar versão pública ou catálogo.

### Etapa 01 (PR #5) — geometria + teste real de Mesh

- A inspeção do IngeTrazo `core.mesh.Mesh` mostrou a necessidade de costurar subdivisões T-junction: faces laterais e requadros compartilham um vértice localizado no interior de aresta não subdividida, o que gerava **arestas abertas / não-manifold** apesar dos 31 testes Python anteriores aprovados.
- Adicionado `OpenTrace_BIM/model.py::_stitch_opening_mesh` no commit `f0f808d`, usando `mesh.interior_vertex_on` + `mesh.split_edge_at` nativos para conectar faces; aplicado só aos geradores com aberturas, preservando o motor normal sem aberturas.
- Testes de integração contra as classes **reais do IngeTrazo + PySide6**, fora da interface gráfica, em `tests_host/test_wall_mesh_host.py` e `.github/workflows/test-wall-mesh-host.yml`: janela retangular, porta acima da altura disponível, janela poligonal, abertura côncava, parede curva e topo inclinado. O primeiro teste acusou 4 falhas de topologia, que a costura corrigiu. [Run 37981091356](https://github.com/lelopes05/opentrace-bim/actions/runs/37981091356): **6 testes de integração OK** depois da correção.
- Na sequência o caso da parede curva passou a utilizar **duas camadas físicas reais** no `build_children()` (commit `be8d906`), confirmadas por [run 37981235121](https://github.com/lelopes05/opentrace-bim/actions/runs/37981235121), `success`.
- Packaging experimental automático **somente após sucesso do gate de malha**: workflow `test-wall-mesh-host.yml` ganhou job `package-experimental` no commit `fdc706f`. Gera `OpenTrace-BIM-Stage01-Aberturas-EXPERIMENTAL.zip`, `SHA256SUMS.txt` e `LEIA_PRIMEIRO.txt` como artefato GitHub Actions; nunca faz release ou atualiza catálogo. Pacote validado/concluído deve ser conferido no run atual antes de informar link para baixar.
- **Ainda precisa de teste visual pelo usuário no IngeTrazo:** lançamento/seleção da nova ferramenta, prévia, edição de vértices/arestas, Undo/Redo, salvar/reabrir `.igz`, tramas/arestas visíveis nos cortes, IFC. Os testes headless comprovam topologia dos casos cobertos, não a UX completa.

### Etapa 02 (PR #7) — base separada, sem UI ainda

- Branch `dev/parametric-door-window-2026-10-09`, aberta como [PR #7](https://github.com/lelopes05/opentrace-bim/pull/7) contra a fundação #3, isolada dos commits da #5 para desenvolvimento paralelo.
- `OpenTrace_BIM/door_window_core.py` (`de63c8e`): especificações JSON-safe, IDs da parede e abertura, `source_id`, âncoras esquerda/centro/direita, dimensão vinculada à âncora, comando único para inverter giro, folha/arco em planta, janela de vidro com montantes e controles de hotspot (largura em todos, altura somente superiores, posição somente inferiores). Não há objeto 3D nem ligação ao `setup()` nesta fase.
- `tests/test_door_window_core.py` (`e9683ef`), workflow `test-door-window.yml` (`6d2a7f1`). [Run 37980967165](https://github.com/lelopes05/opentrace-bim/actions/runs/37980967165): **success** em testes Python e compileall. Registrar quantidade real dos testes a partir do log se necessário.
- **Próximo desenvolvimento 02:** geração real de geometria de folhas/marcos em grupos separados, ligação ao vão da etapa 01 por ID e ferramenta de criação/edição com paleta/hotspots; depois IFC e persistência em `.igz`.

**Regras preservadas:** não mesclar PRs rascunho sem aval; não confundir pacote experimental com release 0.12.9; PRs #3, #4, #5, #6 e #7 continuam com independência documentada.

## Checkpoint verificável — pacote de teste 01 (2026-10-09)

- [Workflow real de malha + pacote, run 37981273027](https://github.com/lelopes05/opentrace-bim/actions/runs/37981273027) concluído com **success** no commit `fdc706f14c15a9719e348c919b283ff382167ce2`.
- Artefato GitHub efetivamente criado, não expirado: `OpenTrace-BIM-Stage01-Aberturas-EXPERIMENTAL` (artifact ID `11640349324`, cerca de 808 KB). Contém ZIP da pasta `OpenTrace_BIM`, `SHA256SUMS.txt` e `LEIA_PRIMEIRO.txt`; para baixar abrir a execução e seção **Artifacts**. Não constitui release publicado.
- O pacote foi gerado **após** o job `host-mesh` passar; a UI no IngeTrazo e edição de projetos `.igz` ainda exigem teste manual. Descompactar em projeto descartável, fazer backup da pasta anterior e não colocar no catálogo público.
- A CI da etapa 02, [run 37980967165](https://github.com/lelopes05/opentrace-bim/actions/runs/37980967165), aprovou `20 tests ... OK` e `compileall`, incluindo os 10 novos testes de portas/janelas; sem GUI/meshes reais.
- **Próxima validação pelo usuário:** 1 parede reta com janela, 1 porta `sill=0` com altura nominal maior que a parede, 1 parede curva com abertura poligonal, 1 abertura concava, edição de vértices/arestas, Ctrl+Z/Refazer e salvar/abrir `.igz`. Verificar contornos limpos com materiais/cortes. Testar em cópia.

## Etapa 02 — geometria 3D independente e host real (2026-10-09)

- Branch `dev/parametric-door-window-2026-10-09`, [PR #7](https://github.com/lelopes05/opentrace-bim/pull/7), separado do 01 (#5) e baseado na fundação (#3).
- **Código 3D efetivamente gravado:** `door_window_geometry.py` (`85f1c85`) constrói no `core.mesh.Mesh` real do IngeTrazo: uma porta de abrir com folha e três partes de marco; uma janela com quadro, vidro e montantes por número de folhas. O conjunto é um `Group` independente, com `host_id`, `opening_id` e registro paramétrico preservados.
- **Posicionamento sem efeitos colaterais:** `place_fill_on_wall()` (`1cb0806`) confere o `source_id` do vão hospedado, dimensões, host UID, âncora esquerda/centro/direita e orienta a esquadria pela trajetória da parede em mundo. Retorna o grupo pronto, **sem** mutar a parede ou a cena. A ferramenta UI que chama EditWall + insere este grupo num único Undo/Redo está pendente.
- **CI real do host:** [run 37981875351](https://github.com/lelopes05/opentrace-bim/actions/runs/37981875351) finalizou `success`: **5 testes de Mesh/Group reais OK**, incluindo colocação de janela em vão de uma parede construída pelo motor atual, bem como geometria 3D fechada de porta e janela. Os testes Python puros da etapa 02 também passaram em [run 37980967165](https://github.com/lelopes05/opentrace-bim/actions/runs/37980967165), **20 tests ... OK**.
- **Gate para integração 02:** ainda não existe objeto de porta/janela acionável pela paleta ou instalado no IngeTrazo. Antes de mesclar os motores, reconciliar a geometria do vão da branch 01 (#5) com a de esquadrias da branch 02 (#7), comandos históricos atômicos, hotspots reais, GUID estável, IFC sem duplicação de objetos de preenchimento e testes `.igz`. A exportação atual cria um preenchimento sem representação na relação IFC; evitar que objeto 3D e a mesma abertura dupliquem IfcDoor/IfcWindow quando integrar.

## Integração experimental das etapas 01–03 (2026-10-10, PR #8)

### Código integrado gravado no GitHub

- PR #7 conciliado com PR #5: `door_window_core.py`, `door_window_geometry.py`, `door_window_commands.py`, `ifc_export.py`, workflows e testes. Porta/janela são objetos `Group` físicos, separados da parede recortada, com `source_id` e `IfcRelFillsElement` vinculados ao `IfcOpeningElement`; evitar duplicar produtos IFC.
- `opening_controller.py`: contorno virtual e seis hotspots por retângulo; livre poligonal expõe vértices. Não existe sólido booleano oculto selecionável nem malha auxiliar persistida. Hit test em coordenadas de tela, sem modificar o modelo.
- `ui.py`: seleção da abertura por contorno ou lista, edição por menu contextual do hotspot; **largura** nos seis pontos, **posição** nos três inferiores, **altura** nos três superiores, operações poligonais preservadas. Paleta radial distingue vão retangular livre, vão de porta sem folha e vão de janela sem esquadria.
- Ferramentas `Porta` e `Janela` no topo e na paleta radial: seleção da parede, três âncoras (esquerda/centro/direita), prévia e confirmação. Um comando `CreateHostedFill` grava recorte e grupo 3D em um passo de histórico. Porta usa `sill=0` por padrão. Paleta exibe opção de trocar âncora (sem deslocar fisicamente) e botão único de inverter giro, ambos undoáveis.
- `DeleteHostedOpening` remove recorte e esquadria em uma transação histórica, restaurando ambos no Undo. `sync_hosted_fill_placements` recalcula a posição após mudança do hospedeiro/nativa e no Undo, sem substituir o `Group` ou sua identidade.
- IDs GUID IFC permanentes criados para novos vãos livres retangulares e poligonais (`wall_opening_tool.py` e `wall_polygon_tool.py`).
- `model.py`: interseção da posição com trajetória via índice `bisect` (antes varredura completa), solução exata de vão em parede reta e custo reduzido de solver curvo; indexação por coordenada de vértice em `_stitch_opening_mesh` para reduzir varredura O(arestas × vértices) ao costurar malhas curvas com camadas.
- `commands.py`: edições somente no recorte preservam os caps/estado derivado existentes quando não há interseções/máscaras complexas, evitando segunda geração completa. `EditHostedFill` não regenera a parede para giro/âncora sem alteração do vão.
- `tests_host/test_opening_integration_host.py`: novo teste sobre `Scene`, malha e matriz reais: dois vãos independentes, seis grips, porta no piso, exclusão/Undo, acompanhamento de deslocamento da parede e controlador em arco.

### Validação automatizada e limites

- Workflow integrado `.github/workflows/test-integrated-openings.yml`: `compileall`, contratos puros e `unittest discover -s tests_host` sobre checkout real do IngeTrazo + PySide6 offscreen. Só se todos passarem publica artefato de instalação **experimental** na execução GitHub Actions, sem release/catálogo.
- Gate headless integrado **confirmado** em [run 38020249245](https://github.com/lelopes05/opentrace-bim/actions/runs/38020249245) no SHA `bd8ebdb5`. A otimização de costura em `18ed278c` é posterior; conferir gate do HEAD antes de chamar qualquer pacote de validado.
- **Ainda pendente:** teste de interface/raster com seleção ativa para isolar o defeito de arestas/VBO/OBB (não houve IngeTrazo visual nesta conversa); testar UX real de todos os hotspots e abas; benchmark de curvas longas; Undo/Redo e `.igz` depois de redimensionar paredes/junções com esquadrias; visualização de múltiplas camadas, perfis inclinados, aberturas concavas; visualização e interpretação IFC externa em Archicad/FreeCAD/Bonsai; regressões após importações reais. Nada disso pode ser anunciado como concluído.
- O motor ainda limita arestas de abertura poligonal a segmentos retos; curvas/chanfros/fillets do contorno livre exigem etapa própria. A parede permanece a autoridade física do recorte; booleanas 3D destrutivas NÃO foram adotadas.
- Nenhuma alteração na `main`, no release público 0.12.9 ou no catálogo. Não fazer merge ou publicar sem validação e autorização.

**Retomada recomendada:** conferir o gate mais recente do [PR #8](https://github.com/lelopes05/opentrace-bim/pull/8) e baixar o ZIP **experimental** do workflow integrado aprovado; validar a seleção e redimensionamento na viewport real, corrigir qualquer artefato de seleção com logs/imagens de reprodução; depois fechar a interoperabilidade IFC e consolidar PRs na ordem da integração aprovada.

### Fechamento do gate automatizado do código integrado — 2026-10-10

- **HEAD de código testado:** `333222b7f35bf3be45c20f973105212140ef26fa`. [GitHub Actions run 38020414977](https://github.com/lelopes05/opentrace-bim/actions/runs/38020414977) terminou com **success** em `pure-tests`, `host-tests` e `experimental-package`.
- **Quantidade comprovada pelos logs:** `43 tests ... OK` em Python puro e **`29 tests ... OK` em IngeTrazo real/PySide6 offscreen**, total **72 testes**; `compileall` também passou.
- Incluem regressões novas de parede **selecionada** ao alterar comprimento e vértice, malha manifold após editar abertura e Undo, vão de porta no piso, edição independente de vãos, exclusão atômica, mover hospedeiro, arco, IFC e persistência `.igz` em testes headless. **Não comprovam** o comportamento raster/OpenGL visível apenas com a seleção ativa no desktop.
- **Pacote automático, experimental e não publicado como release:** artefato `opentrace-integrated-openings-EXPERIMENTAL`, ID `11658221572`, derivado exatamente do SHA verde `333222b7`. Baixar na seção **Artifacts** da execução 38020414977 (login GitHub pode ser exigido). Contém `opentrace-integrated-openings-EXPERIMENTAL.zip` e respectivo `.sha256`.
- Próxima validação MANUAL: em projeto de teste e backup, criar parede reta/curva/multicamadas, porta no piso, janela, vãos livres, selecionar o contorno e editar hotspots, reduzir comprimento e arrastar vértices com a parede selecionada, observar arestas e viewport, curvas longas; validar Undo/Redo, salvar/reabrir e IFC em programa externo. O defeito específico de viewport **não pode ser dado como resolvido antes disso**.
- **Não houve merge, release, alteração no catálogo nem mudança na `main`.** PR #8 permanece draft.
