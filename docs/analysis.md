# ZeroGravity v1.4.2 pro Claude Code s jedním účtem

Stav k 20. listopadu 2026. Zamýšlené nasazení používá jeden účet Antigravity a Claude Code CLI. Rotace účtů do něj nepatří. Audit vychází z veřejných souborů, historie, poznámek k vydáním, hlášení uživatelů a dokumentace Googlu. Proxy ani produkční účet při něm neběžely.

## Co lze z forku převzít

Veřejný repozitář obsahuje Dockerfile, příklad Compose, dokumentaci a distribuční infrastrukturu. Na větvi `main` je 17 sledovaných souborů a 69 commitů. Zdrojové kódy proxy, CLI a překladače požadavků ve zkoumané veřejné historii chybějí. CI dokonce odmítá přítomnost `src/` a `Cargo.toml`. Odkazovaný repozitář `zerogravity-src` nebyl přihlášenému účtu přístupný. Z veřejného forku lze přímo upravit balení a výchozí konfiguraci. Pro cílenou opravu běhové logiky jsou potřeba zdroje nebo vlastní implementace dané části. [Veřejný strom](https://github.com/NikkeTryHard/zerogravity/tree/574e65f) · [CI workflow](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/.github/workflows/safety-check.yml)

Poslední stabilní vydání vyšlo 5. března 2026. Tag `v1.4.2` ukazuje na `26a5df3` s popisem synchronizace v1.4.1. Až následující commit `2c0038b` synchronizoval dokumentaci v1.4.2, mimo jiné opravil popis prahu rotace na 20 % spotřebované kvóty. Pozdější zápisy o dokončených etapách v2 nejsou dokladem o vydání odpovídající binárky. V posledním commitu `574e65f` z 15. dubna autor oznámil přerušení vývoje. Závěrečné ověření shody v2 zůstalo v plánu otevřené. [Rozdíl po tagu](https://github.com/NikkeTryHard/zerogravity/compare/v1.4.2...2c0038b) · [Vydání v1.4.2](https://github.com/NikkeTryHard/zerogravity/releases/tag/v1.4.2) · [Stav projektu](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/README.md)

## Riziko omezení přístupu

Google ve FAQ jmenovitě uvádí používání přihlášení Antigravity v Claude Code. Tato podmínka se vztahuje i na jediný účet. Tým Antigravity popsal obnovu přístupu po dřívější vlně blokací a možnost trvalého zákazu při opakovaném porušení. Issue #99 obsahuje odpověď služby s explicitním důvodem vypnutí kvůli podmínkám. V #97 uživatelé popisují vlastní blokace. Chybí počet všech aktivních účtů a srovnatelná kontrolní skupina, takže z hlášení nelze vypočítat pravděpodobnost zásahu. [FAQ Googlu](https://antigravity.google/docs/faq) · [Vyjádření týmu](https://discuss.ai.google.dev/t/update-on-antigravity-tos-ban/131424) · [#99](https://github.com/NikkeTryHard/zerogravity/issues/99) · [#97](https://github.com/NikkeTryHard/zerogravity/issues/97)

Vydání popisují změny transportu, TLS a zpracování systémových promptů. Dokumentace rozlišuje režimy `native`, `stealth` a `minimal`. Poznámky k vydání v1.4.0 popisují odlišné chování některých operací na pozadí. Veřejné podklady nedokládají příčinnou souvislost mezi blokací a konkrétní verzí backendu, názvem nástroje, promptem, telemetrií nebo síťovým fingerprintem. Aktualizaci těchto částí proto nelze vydávat za záruku proti banu. Google dokumentuje pro programový přístup také Gemini API klíč a přihlašování přes Google Cloud. Použití těchto rozhraní by bylo změnou původního zadání. [Vydání v1.4.0](https://github.com/NikkeTryHard/zerogravity/releases/tag/v1.4.0) · [Vydání v1.4.2](https://github.com/NikkeTryHard/zerogravity/releases/tag/v1.4.2) · [Antigravity SDK](https://antigravity.google/docs/sdk/overview)

## Aktualizace backendu

Dockerfile pro AMD64 i ARM64 stahuje archiv Antigravity `1.18.3-4739469533380608` a vyjímá z něj language server a `product.json`. Google vede oddělené řady pro IDE, aplikaci a CLI. K datu auditu uvádí pro **Antigravity IDE verzi 2.8.0** z 19. listopadu a pro **Antigravity App verzi 2.33.0** ze 17. listopadu. Ani jedno číslo samo neurčuje kompatibilní verzi samostatného language serveru. [Dockerfile](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/Dockerfile) · [Changelog Googlu](https://antigravity.google/docs/changelog)

Aktualizace má vysokou prioritu pro kompatibilitu. Před označením nové kombinace za funkční je potřeba ověřit dostupnost a verzi odpovídajících artefaktů pro obě architektury, start a připravenost procesu, ukončení streamu a alespoň dvě kola volání nástroje. Současný Dockerfile současně bere proxy, CLI a knihovnu z proměnlivého `releases/latest/download` bez kontroly očekávaného hashe. Compose používá image `latest`. Pro srovnatelný výsledek je potřeba zaznamenat verzi backendu i přesný digest testované distribuce. [Dockerfile](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/Dockerfile) · [Compose](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/docker-compose.example.yml)

## Provoz jednoho účtu

- **Přístup k proxy.** Ukázkový Compose publikuje porty 8741 a 443 bez omezení na localhost. API klíč může zůstat prázdný a dokumentace v takovém případě uvádí vypnutí autentizace. Na síťově dosažitelném hostiteli tak může cizí provoz čerpat kvótu vlastníka. Pro lokální Claude Code dává smysl omezit publikované rozhraní na místní počítač. [Compose](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/docker-compose.example.yml) · [Dokumentace API](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/docs/api.md#api-key-protection)
- **Ochrana údajů.** Ukázková konfigurace očekává vedle Compose soubor `accounts.json` s dlouhodobým refresh tokenem. Projektové soubory `.gitignore` a `.dockerignore` jej nevylučují. Při běžném hromadném přidání souborů může skončit ve veřejném forku, při lokálním sestavení v kontextu Dockeru. Ve sledovaných souborech zkoumaného klonu nebyl. [Pravidla Gitu](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/.gitignore) · [Pravidla Dockeru](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/.dockerignore)
- **Chyby autentizace.** Podle vydání v1.4.2 proxy při `401` zkusí obnovit access token i s jediným účtem. Při `403` je důležité zachovat důvod vrácený poskytovatelem. Explicitní zákaz služby má ukončit operaci včetně dalších pokusů přes jiný model. Samotný stav `403` k diagnóze banu nestačí. Dokumentovaná okamžitá rotace po `403` se týká sestav se dvěma a více účty. Z #99 nelze poznat, která vrstva spustila další pokusy. [Vydání v1.4.2](https://github.com/NikkeTryHard/zerogravity/releases/tag/v1.4.2) · [Rotace účtů](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/docs/api.md#account-rotation) · [#99](https://github.com/NikkeTryHard/zerogravity/issues/99)
- **Fronta a opakování.** Výchozí fronta je zapnutá, povoluje dva souběžné požadavky, pojme 50 čekajících požadavků, nemá minimální odstup a čekání může trvat deset minut. Pro diagnostiku zamrznutí je důležité měřit dobu ve frontě, čekání na první událost a ukončení streamu zvlášť. Historické #24 doložilo 1 289 upstream volání ze 75 klientských požadavků a reportér pak potvrdil opravu ve v1.1.9. Jde o důvod testovat celkový počet pokusů na operaci. Čísla charakterizují starší vydání. [Nastavení fronty](https://github.com/NikkeTryHard/zerogravity/blob/574e65f/docs/docker.md) · [#24](https://github.com/NikkeTryHard/zerogravity/issues/24)

## Posouzení issues

Přehled zahrnoval 95 issues, z toho deset otevřených. U souvisejících uzavřených hlášení je podstatný také důvod uzavření a výsledek posledního testu reportéra.

| Hlášení | Zjištění a rozhodnutí pro jeden účet |
| --- | --- |
| [#108](https://github.com/NikkeTryHard/zerogravity/issues/108), [#104](https://github.com/NikkeTryHard/zerogravity/issues/104) | Vysoká priorita. Původní report s dokumentovanou cestou rozlišuje funkční chat přes dočasný token a prázdný seznam spravovaných účtů. Stav přetrval i po odstranění prázdné proměnné z image. #104 bylo uzavřeno ve prospěch #108. Pozdější komentář používá jinou cestu připojení souboru. Ověřit obnovitelnost přihlášení odděleně od dostupnosti procesu. |
| [#109](https://github.com/NikkeTryHard/zerogravity/issues/109), [#100](https://github.com/NikkeTryHard/zerogravity/issues/100) | Pro Claude Code prioritní reprodukce. #109 hlásí zamrznutí po několika dotazech, ale postrádá časování a identifikaci image. #100 řešilo tiché ukončení velkého požadavku, pro které v1.4.2 uvádí změnu na explicitní chybu 504. Vztah k #108 zůstává neověřený. |
| [#106](https://github.com/NikkeTryHard/zerogravity/issues/106), [#102](https://github.com/NikkeTryHard/zerogravity/issues/102), [#110](https://github.com/NikkeTryHard/zerogravity/issues/110) | Tři různé projevy v jiných klientech. #106 popisuje nesoulad jména nástroje ve druhém kole a bylo uzavřeno jako `not planned`. #102 hlásí prázdný argument při zápisu souboru na v1.4.1. #110 popisuje textový JSON místo vykonatelné události v OpenClaw. Pro Claude Code z toho plyne test názvu, argumentů, typu události a návaznosti výsledku přes dvě kola. V1.4.1 navíc uvádí záměrné potlačení nástrojů u některých klientů. [Poznámky k v1.4.1](https://github.com/NikkeTryHard/zerogravity/releases/tag/v1.4.1) |
| [#94](https://github.com/NikkeTryHard/zerogravity/issues/94), [#103](https://github.com/NikkeTryHard/zerogravity/issues/103) | #94 žádá automatické opakování po 503. Je potřeba rozlišit plnou lokální frontu, vyčerpanou kapacitu modelu a restart procesu. Opakování po předání části streamu může zdvojit výstup nebo nástrojovou akci. U #103 reportér nakonec potvrdil dočasný stav 503 a následné automatické zotavení. Má smysl testovat délku a dokončení obnovy. |
| [#97](https://github.com/NikkeTryHard/zerogravity/issues/97), [#99](https://github.com/NikkeTryHard/zerogravity/issues/99) | Relevantní důkazy o výskytu blokací. #99 dokládá explicitní odpověď služby, #97 obsahuje svědectví více uživatelů. Příčinu jednotlivých rozhodnutí Googlu z těchto hlášení určit nelze. |
| [#87](https://github.com/NikkeTryHard/zerogravity/issues/87), [#17](https://github.com/NikkeTryHard/zerogravity/issues/17), [#26](https://github.com/NikkeTryHard/zerogravity/issues/26) | #87 navrhuje výběr dalšího účtu podle dostupné kvóty a pro toto nasazení je mimo rozsah. #17 a #26 jsou organizační oznámení. |

## Připravenost k úpravám

Pro distribuční část jsou konkrétní první práce identifikované: omezit výchozí síťovou dostupnost, vyloučit lokální údaje z Gitu a kontextu sestavení a připnout binární artefakty. U backendu je dalším krokem ověření kompatibility aktuální distribuce IDE. U běhových chyb mají pro jeden účet nejvyšší hodnotu rozlišení dočasného a obnovitelného přihlášení, správné ukončení po explicitním zákazu a vícekolový test Claude Code. Skutečná kompatibilita nového backendu a přesné příčiny hlášených běhových chyb zůstávají neověřené.

## Výsledek úprav ve forku

### Načtení účtu ve v1.4.2

Čtyři starty stejné AMD64 binárky s vypnutou vnější sítí a fiktivním účtem ukázaly konkrétní příčinu prázdného seznamu. Měnila se pouze dvě pole ve vstupním JSON. Ve všech čtyřech případech odpověděl `/health` stavem 200.

| Pole kromě e-mailu a refresh tokenu | `GET /v1/accounts` | `GET /v1/accounts/status` |
| --- | --- | --- |
| Žádné | Prázdný seznam | `active_index: null` |
| Jen `active` | Prázdný seznam | `active_index: null` |
| Jen `extracted_at` | Jeden účet s `active: false` | `active_index: 0` |
| `extracted_at` i odpovídající `active` | Jeden účet s `active: true` | `active_index: 0` |

To vysvětluje, jak může ručně vytvořený soubor podle původně zveřejněného schématu vyvolat stejný příznak jako #108. Obsah skutečného souboru reportéra k dispozici nebyl. Samotné zobrazení aktivního účtu uspělo i s neplatným tokenem, takže pro ověření obnovy je třeba sledovat výsledek skutečného obnovení.

Další testy ukázaly prázdný seznam i při nesprávném typu volitelného pole, například `alias: true` nebo `disabled: 7`. S hodnotou `disabled: true` binárka účet načetla jako zakázaný. Spouštěcí skript nyní tyto vstupy odmítne před startem a zachová původní soubor.

### Claude Code, stream a opakování

Claude Code 2.1.330 běžel v izolovaném kontejneru bez přístupu k síti poskytovatele. Lokální náhrada Messages API poslala dvě po sobě jdoucí události `tool_use` pro nástroj `Read`. Klient načetl dva různé testovací soubory. Server v navazujících požadavcích ověřil ID a obsah obou výsledků a ukončil třetí stream.

| Odpověď testovacího serveru | Pozorování u klienta |
| --- | --- |
| HTTP 403 s explicitním vypnutím služby | Jeden požadavek. Klient zobrazil důvod poskytovatele a skončil. |
| Událost chyby po prvním textu ve streamu | S vypnutým přechodem na nestreamovanou odpověď klient skončil po jednom požadavku. |
| Přerušený HTTP přenos po první části textu | S výchozím počtem opakování klient znovu odeslal bajtově shodný streamovaný požadavek. S `CLAUDE_CODE_MAX_RETRIES=0` skončil po prvním pokusu. |
| Dvakrát HTTP 503 před prvním výstupem, potom úspěch | Při výchozím počtu opakování klient poslal první požadavek celkem třikrát. Po přibližně třech sekundách pokračoval a dokončil obě kola nástroje. |

Počty odpovídají spojení mezi klientem a testovacím serverem. Skutečný počet volání mezi binární proxy a poskytovatelem při jedné operaci vyžaduje samostatné měření. Diagnostický skript posílá na každé kolo jeden požadavek, vyhodnocuje také ukončení HTTP přenosu a po chybě zastaví další kola. [Návod a příkazy](clients.md#diagnosing-a-single-account-session)

### Distribuce a výběr backendu

Fork připíná proxy, CLI a knihovnu na v1.4.2. Dockerfile kontroluje SHA-256 stažených souborů pro každou architekturu, používá Debian připnutý digestem a datovaný snímek balíčků. Při testu záměrně chybný kontrolní součet sestavení zastavil. Kontrolní součty obou balíčků IDE 1.20.6 odpovídaly podepsaným metadatům repozitáře Googlu.

| Verze IDE | Výsledek ověření s proxy v1.4.2 |
| --- | --- |
| 1.18.3 | Výchozí backend. Start, lokální API, spravovaný účet a restart prošly na AMD64. |
| 1.18.4, 1.19.4 a 1.19.6 | Na AMD64 prošla kontrola startu procesu a načtení syntetického účtu. |
| 1.20.6 | Nejnovější úspěšně spuštěný kandidát z testovaných verzí. V Compose lze zvolit přes `ZEROGRAVITY_BACKEND=1.20.6`. |
| 1.21.6, 1.21.9, 1.22.2 a 1.23.2 | V rozhraní příkazové řádky na AMD64 chybí přepínač `-server_port`, který proxy používá při startu. Při spuštění image 1.23.2 proces tento přepínač výslovně odmítl. |
| 2.8.0 | Oficiální archivy IDE pro AMD64 i ARM64 neobsahují samostatný language server na vyžadovaném místě ani jinou binárku stejného jména. |

Digests níže identifikují konkrétní platformní manifesty lokálně sestavených a otestovaných image. Compose při sestavení přidává vlastní popisky, takže jeho manifest může mít jiný digest než při přímém `docker build`.

| Architektura a způsob sestavení | Výchozí 1.18.3 | Volitelná 1.20.6 |
| --- | --- | --- |
| AMD64, Compose | `sha256:75031ffbb6840ef850f5402b3ee248bfc9252a568c2f89ffb836098f5fc5c202` | `sha256:a94ac2540b9875ed748369bc7ad61b66cf10aa08766013d48e31f34201725f65` |
| ARM64, Buildx s emulací QEMU | `sha256:4fd05842d8e4d78549ec4f88f13adc86896d3088dbd00216f61bc777b06e4aff` | `sha256:404eadf34b437c32aea6b255e8b93214511466e4d7cc0ed7b034ef9f971a04b9` |

### Provozní změny a otevřené ověření

Compose zpřístupňuje pouze `127.0.0.1:8741`, vyžaduje API klíč a při startu kontroluje právě jeden povolený účet. Chybějící `active` a `extracted_at` doplní do soukromé kopie v paměti. Kontrola po restartu porovnává zdrojový soubor s původním vstupem po bajtech. Git i Docker vylučují lokální soubory s účty a přihlašovacími údaji. Fronta připouští jeden běžící požadavek, čtyři čekající, odstup 500 ms a nejvýše 30 s čekání. [Nastavení a návod](docker.md)

Na AMD64 prošly obě sestavy kontrolou běžícího language serveru, odmítnutím požadavku bez API klíče, výpisem modelů s klíčem a načtením účtu před i po restartu. Požadavek na generování s fiktivním účtem ve vypnuté síti skončil očekávanou chybou 401 s důvodem `No OAuth token`. Při záměrně vypnutém automatickém restartu jsme u původní binárky pozorovali občasné ukončení language serveru během startu. S nastavením Compose `unless-stopped` prošlo pět opakovaných kontrol výchozího image.

Na ARM64 prošly stejné kontroly obou image v emulaci QEMU bez přístupu k síti. Při jednom měření potřeboval výchozí backend k prvnímu úspěšnému startu pět automatických restartů, novější dva. Po následném ručním restartu byly oba připravené bez dalšího automatického restartu. Smoke test sleduje připravenost až 90 sekund a vypisuje dobu čekání i počet restartů.

Lokálně prošly také kontroly CI pro distribuci, vstupní konfiguraci a 13 testů diagnostiky, včetně předčasně ukončeného HTTP přenosu po události `message_stop`. Ručně spustitelný workflow pokrývá obě verze backendu na nativních runnerech AMD64 a ARM64. [Workflow](../.github/workflows/safety-check.yml)

Otevřeným bodem je ověření obnovy OAuth přes skutečnou expiraci a celého streamu přes poskytovatele v prostředí s povoleným přístupem. Rozhodnutí o povýšení 1.20.6 na výchozí verzi závisí na tomto výsledku. K cílené opravě interních opakování po 403/503, překladu nástrojů a příčiny zamrzání v #109 chybějí ve veřejném forku zdroje proxy a překladače.
