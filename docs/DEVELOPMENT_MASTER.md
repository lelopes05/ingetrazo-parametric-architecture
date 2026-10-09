# OpenTrace BIM — Registro mestre de desenvolvimento

**Referência:** 2026-10-09 · **Repositório:** `lelopes05/opentrace-bim` · **Release preservado:** 0.12.9

> Abrir a próxima conversa lendo este arquivo na branch/PR de desenvolvimento mais recente. Validar commits/arquivos reais antes de declarar algo integrado. Atualizar este registro ao fechar cada bloco.

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
