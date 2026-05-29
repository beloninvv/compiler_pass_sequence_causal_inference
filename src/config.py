#!/usr/bin/env python3
"""
Конфигурация проекта: пути LLVM, список проходов, параметры эксперимента.
"""

from pathlib import Path

# ── Пути ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
LLVM_BIN = "/opt/homebrew/opt/llvm@16/bin"
OPT = f"{LLVM_BIN}/opt"
LLVM_DIS = f"{LLVM_BIN}/llvm-dis"

BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks" / "compiled"
RESULTS_DIR = PROJECT_ROOT / "experiments" / "results"

# ── Параметры эксперимента ────────────────────────────────────────────────

NUM_ITERATIONS = 10_000       # прогонов на бенчмарк
MIN_SEQ_LENGTH = 10           # минимальная длина последовательности
MAX_SEQ_LENGTH = 40           # максимальная длина последовательности
SEED = 42                     # для воспроизводимости
OPT_TIMEOUT = 60              # таймаут opt в секундах

# ── Перемешиваемые проходы (89 штук) ─────────────────────────────────────
# Все проверены в legacy PM LLVM 16.
# -enable-new-pm=0 добавляется отдельно как фиксированный флаг.

PASSES = [
    # Из -Oz (33):
    "bdce", "ipsccp", "correlated-propagation", "mem2reg", "sroa",
    "instsimplify", "constmerge", "function-attrs", "deadargelim",
    "globaldce", "elim-avail-extern", "mergefunc", "instcombine",
    "simplifycfg", "tailcallelim", "reassociate", "memcpyopt", "sccp",
    "dce", "adce", "dse", "jump-threading", "loop-idiom", "loop-deletion",
    "gvn", "gvn-hoist", "gvn-sink", "newgvn", "early-cse", "mergereturn",
    "globalopt", "strip-dead-prototypes", "indvars",

    # Расширение от научника (14):
    "mergeicmps", "separate-const-offset-from-gep", "libcalls-shrinkwrap",
    "flattencfg", "loop-reduce", "loop-unroll", "loop-rotate",
    "partial-inliner", "lower-expect", "alignment-from-assumptions",
    "rpo-function-attrs", "attributor", "inferattrs",
    "called-value-propagation",

    # Добавленные — базовые (4):
    "licm", "loop-simplify", "div-rem-pairs", "float2int",

    # Добавленные — инлайнинг, векторизация, скалярные (23):
    "inline", "sink", "loop-vectorize", "slp-vectorizer",
    "callsite-splitting", "dfa-jump-threading", "consthoist",
    "mldst-motion", "slsr", "loop-interchange", "loop-fusion",
    "loop-distribute", "loop-load-elim", "loop-sink",
    "loop-unroll-and-jam", "hotcoldsplit", "irce", "nary-reassociate",
    "scalarizer", "vector-combine", "always-inline", "globalsplit",
    "lowerswitch",

    # Добавленные — loop-оптимизации и вспомогательные (15):
    "early-cse-memssa", "simple-loop-unswitch", "loop-versioning",
    "loop-flatten", "loop-reroll", "loop-instsimplify", "loop-simplifycfg",
    "loop-predication", "speculative-execution",
    "partially-inline-libcalls", "load-store-vectorizer", "iroutliner",
    "global-merge", "break-crit-edges", "unreachableblockelim",
]

assert len(PASSES) == 89, f"Ожидалось 89 проходов, получено {len(PASSES)}"

# ── Ручная классификация бенчмарков по доменам (per-class) ───────────────
# 8 классов: crypto, numeric, multimedia, loop_bench, pointer_data,
#            string_parse, systems, general

# Класс по умолчанию для целых наборов
_SUITE_CLASSES: dict[str, str] = {
    "polybench":     "numeric",
    "tsvc":          "loop_bench",
    "mediabench":    "multimedia",
    "olden":         "pointer_data",
    "ptrdist":       "pointer_data",
    "dhrystone":     "general",
    "npb-serial":    "general",
    "mallocbench":   "general",
}

# Индивидуальные назначения для смешанных наборов
_INDIVIDUAL_CLASSES: dict[str, str] = {
    # ── cbench ──
    "cbench__automotive_bitcount":     "crypto",
    "cbench__automotive_qsort1":       "general",
    "cbench__automotive_susan_c":      "multimedia",
    "cbench__automotive_susan_e":      "multimedia",
    "cbench__automotive_susan_s":      "multimedia",
    "cbench__bzip2d":                  "general",
    "cbench__bzip2e":                  "general",
    "cbench__consumer_jpeg_c":         "multimedia",
    "cbench__consumer_jpeg_d":         "multimedia",
    "cbench__consumer_lame":           "multimedia",
    "cbench__consumer_tiff2bw":        "multimedia",
    "cbench__consumer_tiff2rgba":      "multimedia",
    "cbench__consumer_tiffdither":     "multimedia",
    "cbench__consumer_tiffmedian":     "multimedia",
    "cbench__network_dijkstra":        "pointer_data",
    "cbench__office_stringsearch1":    "string_parse",
    "cbench__security_blowfish_d":     "crypto",
    "cbench__security_blowfish_e":     "crypto",
    "cbench__security_rijndael_d":     "crypto",
    "cbench__security_rijndael_e":     "crypto",
    "cbench__security_sha":            "crypto",
    "cbench__telecom_CRC32":           "crypto",
    "cbench__telecom_adpcm_c":         "multimedia",
    "cbench__telecom_adpcm_d":         "multimedia",
    "cbench__telecom_gsm":             "multimedia",
    # ── mibench ──
    "mibench__automotive-basicmath":   "numeric",
    "mibench__automotive-bitcount":    "crypto",
    "mibench__automotive-susan":       "multimedia",
    "mibench__consumer-jpeg":          "multimedia",
    "mibench__consumer-lame":          "multimedia",
    "mibench__network-dijkstra":       "pointer_data",
    "mibench__network-patricia":       "pointer_data",
    "mibench__office-stringsearch":    "string_parse",
    "mibench__security-blowfish":      "crypto",
    "mibench__security-rijndael":      "crypto",
    "mibench__security-sha":           "crypto",
    "mibench__telecomm-CRC32":         "crypto",
    "mibench__telecomm-FFT":           "numeric",
    # ── prolangs-c ──
    "prolangs-c__agrep":               "string_parse",
    "prolangs-c__allroots":            "numeric",
    "prolangs-c__archie-client":       "systems",
    "prolangs-c__assembler":           "string_parse",
    "prolangs-c__bison":               "string_parse",
    "prolangs-c__cdecl":               "string_parse",
    "prolangs-c__fixoutput":           "string_parse",
    "prolangs-c__football":            "general",
    "prolangs-c__gnugo":               "general",
    "prolangs-c__plot2fig":            "general",
    "prolangs-c__unix-smail":          "systems",
    "prolangs-c__unix-tbl":            "string_parse",
    # ── misc ──
    "misc__ReedSolomon":               "crypto",
    "misc__dt":                        "general",
    "misc__evalloop":                  "general",
    "misc__fbench":                    "numeric",
    "misc__ffbench":                   "numeric",
    "misc__flops":                     "numeric",
    "misc__flops-1":                   "numeric",
    "misc__flops-2":                   "numeric",
    "misc__flops-3":                   "numeric",
    "misc__flops-4":                   "numeric",
    "misc__flops-5":                   "numeric",
    "misc__flops-6":                   "numeric",
    "misc__flops-7":                   "numeric",
    "misc__flops-8":                   "numeric",
    "misc__fp-convert":                "numeric",
    "misc__himenobmtxpa":              "numeric",
    "misc__lowercase":                 "string_parse",
    "misc__mandel":                    "numeric",
    "misc__mandel-2":                  "numeric",
    "misc__matmul_f64_4x4":            "numeric",
    "misc__oourafft":                  "numeric",
    "misc__perlin":                    "numeric",
    "misc__pi":                        "numeric",
    "misc__revertBits":                "crypto",
    "misc__richards_benchmark":        "general",
    "misc__salsa20":                   "crypto",
    "misc__whetstone":                 "numeric",
    # ── shootout ──
    "shootout__ackermann":             "general",
    "shootout__ary3":                  "general",
    "shootout__fib2":                  "general",
    "shootout__hash":                  "general",
    "shootout__heapsort":              "general",
    "shootout__hello":                 "general",
    "shootout__lists":                 "pointer_data",
    "shootout__matrix":                "numeric",
    "shootout__methcall":              "general",
    "shootout__nestedloop":            "general",
    "shootout__objinst":               "general",
    "shootout__random":                "general",
    "shootout__sieve":                 "general",
    "shootout__strcat":                "string_parse",
    # ── stanford ──
    "stanford__Bubblesort":            "general",
    "stanford__FloatMM":               "numeric",
    "stanford__IntMM":                 "numeric",
    "stanford__Oscar":                 "general",
    "stanford__Puzzle":                "general",
    "stanford__Queens":                "general",
    "stanford__Quicksort":             "general",
    "stanford__RealMM":                "numeric",
    "stanford__Towers":                "general",
    "stanford__Treesort":              "pointer_data",
    # ── trimaran ──
    "trimaran__enc-3des":              "crypto",
    "trimaran__enc-md5":               "crypto",
    "trimaran__enc-pc1":               "crypto",
    "trimaran__enc-rc4":               "crypto",
    "trimaran__netbench-crc":          "crypto",
    "trimaran__netbench-url":          "string_parse",
    # ── bitbench ──
    "bitbench__drop3":                 "crypto",
    "bitbench__five11":                "crypto",
    "bitbench__uudecode":              "crypto",
    "bitbench__uuencode":              "crypto",
    # ── coyotebench ──
    "coyotebench__almabench":          "numeric",
    "coyotebench__huffbench":          "crypto",
    "coyotebench__lpbench":            "numeric",
    # ── benchmarkgame ──
    "benchmarkgame__fannkuch":         "general",
    "benchmarkgame__n-body":           "numeric",
    "benchmarkgame__nsieve-bits":      "crypto",
    "benchmarkgame__partialsums":      "numeric",
    "benchmarkgame__puzzle":           "general",
    "benchmarkgame__recursive":        "general",
    "benchmarkgame__spectral-norm":    "numeric",
    # ── doe_proxyapps_c ──
    "doe_proxyapps_c__Pathfinder":     "numeric",
    "doe_proxyapps_c__RSBench":        "numeric",
    "doe_proxyapps_c__SimpleMOC":      "numeric",
    "doe_proxyapps_c__XSBench":        "numeric",
    "doe_proxyapps_c__miniGMG":        "numeric",
    # ── asc_sequoia ──
    "asc_sequoia__AMGmk":              "numeric",
    "asc_sequoia__CrystalMk":          "numeric",
    # ── mccat ──
    "mccat__01-qbsort":                "general",
    "mccat__03-testtrie":              "pointer_data",
    "mccat__04-bisect":                "numeric",
    "mccat__05-eks":                   "general",
    "mccat__08-main":                  "general",
    "mccat__09-vor":                   "numeric",
    "mccat__12-IOtest":                "general",
    "mccat__15-trie":                  "pointer_data",
    "mccat__17-bintr":                 "pointer_data",
    # ── mcgill ──
    "mcgill__chomp":                   "general",
    "mcgill__exptree":                 "pointer_data",
    "mcgill__misr":                    "general",
    "mcgill__queens":                  "general",
    # ── versabench ──
    "versabench__8b10b":               "crypto",
    "versabench__bmm":                 "numeric",
    "versabench__dbms":                "systems",
    "versabench__ecbdes":              "crypto",
    # ── stb ──
    "stb__cave_render":                "multimedia",
    "stb__stb_vorbis":                 "multimedia",
    # ══════════════════════════════════════════════════════════════════════
    # AnghaBench: переопределения по файлу/функции (вместо проекта).
    # Формат имени: anghabench__<project>__extr_<file>_c_<function>
    # ══════════════════════════════════════════════════════════════════════
    # ── → string_parse (парсеры, лексеры, форматирование, аргументы) ──
    "anghabench__AppImageKit__extr_appimagetool_c_extract_arch_from_text":    "string_parse",
    "anghabench__Arduino__extr_ip_addr_c_ipaddr_aton":                        "string_parse",
    "anghabench__Cello__extr_regexp9_c_evaluntil":                            "string_parse",
    "anghabench__Craft__extr_sqlite3_c_substrFunc":                           "string_parse",
    "anghabench__How-to-Make-a-Computer-Operating-System__extr_getopt_c__getopt_initialize": "string_parse",
    "anghabench__How-to-Make-a-Computer-Operating-System__extr_getopt_c_exchange":           "string_parse",
    "anghabench__Provenance__extr_sh2rec_c_generateMOVWI":                    "string_parse",
    "anghabench__TDengine__extr_isoir165ext_h_isoir165ext_wctomb":            "string_parse",
    "anghabench__git__extr_wt_status_c_wt_longstatus_print_tracking":         "string_parse",
    "anghabench__h2o__extr_parson_c_parse_object_value":                      "string_parse",
    "anghabench__http-parser__extr_http_parser_c_http_parse_host":            "string_parse",
    "anghabench__http-parser__extr_http_parser_c_http_parse_host_char":       "string_parse",
    "anghabench__japronto__extr_picohttpparser_c_get_token_to_eol":           "string_parse",
    "anghabench__lwan__extr_techempower_c_fortune_list_generator":            "string_parse",
    "anghabench__lz4__extr_lz4cli_c_usage_advanced":                          "string_parse",
    "anghabench__macvim__extr_if_py_both_h_OptionsItem":                      "string_parse",
    "anghabench__masscan__extr_out_ndjson_c_ndjson_out_banner":               "string_parse",
    "anghabench__masscan__extr_ranges_c_rangelist_parse_ports":               "string_parse",
    "anghabench__memcached__extr_memcached_c_process_arithmetic_command":      "string_parse",
    "anghabench__mongoose__extr_sqlite3_c_substrFunc":                        "string_parse",
    "anghabench__mpv__extr_m_option_c_parse_channels":                        "string_parse",
    "anghabench__nanomsg__extr_options_c_nn_parse_long_option":               "string_parse",
    "anghabench__netdata__extr_benchmark_line_parsing_c_test4":               "string_parse",
    "anghabench__nodemcu-firmware__extr_llex_c_read_string":                  "string_parse",
    "anghabench__php-src__extr_zend_dump_c_zend_dump_block_header":           "string_parse",
    "anghabench__php-src__extr_zend_inheritance_c_do_inherit_class_constant": "string_parse",
    "anghabench__phpredis__extr_library_c_redis_unpack":                      "string_parse",
    "anghabench__reactos__extr_StrAddr_c_AddrToAddrStr":                      "string_parse",
    "anghabench__reactos__extr_hlsl_tab_c_create_loop":                       "string_parse",
    "anghabench__redis__extr_llex_c_read_string":                             "string_parse",
    "anghabench__redshift__extr_options_c_print_help":                        "string_parse",
    "anghabench__rofi__extr_script_c_script_switcher_parse_setup":            "string_parse",
    "anghabench__streem__extr_time_c_time_str":                               "string_parse",
    "anghabench__tg__extr_interface_c_print_user_name":                       "string_parse",
    "anghabench__the_silver_searcher__extr_ignore_c_add_ignore_pattern":      "string_parse",
    "anghabench__tig__extr_help_c_help_draw":                                 "string_parse",
    "anghabench__tini__extr_tini_c_parse_args":                               "string_parse",
    "anghabench__tmux__extr_names_c_check_window_name":                       "string_parse",
    "anghabench__torch7__extr_luaT_c_luaT_stackdump":                        "string_parse",
    "anghabench__wrk__extr_http_parser_c_http_parse_host":                    "string_parse",
    "anghabench__wrk__extr_wrk_c_parse_args":                                 "string_parse",
    # ── → pointer_data (аллокаторы, деревья, хеш-таблицы) ──
    "anghabench__Arduino__extr_pbuf_c_pbuf_realloc":                          "pointer_data",
    "anghabench__anypixel__extr_mem_c_mem_free":                              "pointer_data",
    "anghabench__ccv__extr_sqlite3_c_pcache1Create":                          "pointer_data",
    "anghabench__db_tutorial__extr_db_c_create_new_root":                     "pointer_data",
    "anghabench__db_tutorial__extr_db_c_internal_node_insert":                "pointer_data",
    "anghabench__gb-studio__extr_realloc_c_realloc":                          "pointer_data",
    "anghabench__git__extr_revision_c_leave_one_treesame_to_parent":          "pointer_data",
    "anghabench__postgres__extr_nbtxlog_c_btree_xlog_newroot":                "pointer_data",
    "anghabench__proxychains-ng__extr_allocator_thread_c_ip_from_internal_list": "pointer_data",
    "anghabench__rufus__extr_alloc_stats_c_ext2fs_block_alloc_stats_range":   "pointer_data",
    "anghabench__streem__extr_node_c_node_free":                              "pointer_data",
    "anghabench__tig__extr_hashtab_c_htab_expand":                            "pointer_data",
    # ── → multimedia (рендеринг, аудио, видео, игры) ──
    "anghabench__RetroArch__extr_spdif_c_spdif_input_port_format_commit":     "multimedia",
    "anghabench__esp-idf__extr_btc_a2dp_sink_c_btc_a2dp_sink_enque_buf":      "multimedia",
    "anghabench__gb-studio__extr_Scene_b_c_SceneUpdateActorMovement_b":       "multimedia",
    "anghabench__ijkplayer__extr_android_nativewindow_c_android_render_yv12_on_yv12": "multimedia",
    "anghabench__ijkplayer__extr_ijkiourlhook_c_ijkio_urlhook_call_inject":   "multimedia",
    "anghabench__nginx-rtmp-module__extr_ngx_rtmp_mp4_c_ngx_rtmp_mp4_write_tkhd":           "multimedia",
    "anghabench__nginx-rtmp-module__extr_ngx_rtmp_record_module_c_ngx_rtmp_record_publish":  "multimedia",
    "anghabench__nginx__extr_ngx_http_mp4_module_c_ngx_http_mp4_update_ctts_atom":           "multimedia",
    "anghabench__rofi__extr_textbox_c_textbox_initialize_font":               "multimedia",
    "anghabench__oss-fuzz__extr_fuzz_h_ExtractWebPConfig":                    "multimedia",
    # ── → crypto (шифрование, base64, сжатие, хеширование) ──
    "anghabench__arduino-esp32__extr_cdecode_c_base64_decode_block_signed":    "crypto",
    "anghabench__hiredis__extr_ssl_c_redisSSLConnect":                        "crypto",
    "anghabench__linux__extr_safexcel_cipher_c_safexcel_aead_ccm_setkey":     "crypto",
    "anghabench__nginx__extr_ngx_http_gzip_filter_module_c_ngx_http_gzip_filter_deflate_start": "crypto",
    "anghabench__robotgo__extr_base64_c_base64decode":                        "crypto",
    "anghabench__robotgo__extr_base64_c_base64encode":                        "crypto",
    "anghabench__the_silver_searcher__extr_decompress_c_is_zipped":           "crypto",
    # ── → numeric (вычисления, математика) ──
    "anghabench__jq__extr_decNumber_c_decNumberInvert":                       "numeric",
    "anghabench__jq__extr_decNumber_c_decNumberReduce":                       "numeric",
    "anghabench__libevent__extr_watch_timing_c_histogram_query":              "numeric",
    "anghabench__sumatrapdf__extr_cmspack_c_PackHalfFromFloat":               "numeric",
    "anghabench__timescaledb__extr_deltadelta_c_delta_delta_from_parts":      "numeric",
    # ── → general (утилиты, игровая логика, разное) ──
    "anghabench__Cello__extr_sudoku_c_c_sd_solve":                            "general",
    "anghabench__GloVe__extr_shuffle_c_shuffle_by_chunks":                    "general",
    "anghabench__Provenance__extr_yuirange_c_yui_range_new":                  "general",
    "anghabench__SoftEtherVPN__extr_Kernel_c_c_mkgmtime":                     "general",
    "anghabench__borg__extr_divsufsort_c_sssort":                             "general",
    "anghabench__darknet__extr_go_c_run_go":                                  "general",
    "anghabench__obs-studio__extr_test_copy_c_test_copy_simple":              "general",
    "anghabench__zstd__extr_divsufsort_c_sssort":                             "general",
    # ── → systems (из других классов, но по функции — системный код) ──
    "anghabench__DOOM__extr_d_net_c_NetUpdate":                               "systems",
    "anghabench__GloVe__extr_cooccur_c_merge_files":                          "systems",
    "anghabench__exploitdb__extr_43987_c_RegisterProcessByIOCTL":             "systems",
    "anghabench__lz4__extr_lz4io_c_LZ4IO_openDstFile":                       "systems",
    "anghabench__mimikatz__extr_sqlite3_omit_c_clearDatabasePage":            "systems",
    "anghabench__progress__extr_progress_c_find_pids_by_binary_name":         "systems",
    "anghabench__progress__extr_progress_c_main":                             "systems",
    "anghabench__scrcpy__extr_input_manager_c_input_manager_process_mouse_button": "systems",
    "anghabench__upx__extr_i386_openbsd_elf_main_c_xfind_pages":              "systems",
    "anghabench__vlc__extr_ftp_c_Connect":                                    "systems",
}

# Класс AnghaBench-проекта по домену исходного репозитория
_ANGHA_PROJECT_CLASSES: dict[str, str] = {
    # crypto / security
    "hashcat": "crypto", "openssl": "crypto", "libsodium": "crypto",
    "meltdown": "crypto", "exploitdb": "crypto", "mimikatz": "crypto",
    # multimedia / graphics
    "FFmpeg": "multimedia", "HandBrake": "multimedia", "mozjpeg": "multimedia",
    "vlc": "multimedia", "obs-studio": "multimedia", "Cinder": "multimedia",
    "nuklear": "multimedia", "darknet": "multimedia", "scrcpy": "multimedia",
    "openpilot": "multimedia", "sumatrapdf": "multimedia", "libui": "multimedia",
    "ffmpeg-libav-tutorial": "multimedia",
    # numeric / scientific
    "numpy": "numeric", "pifs": "numeric", "GloVe": "numeric",
    "torch7": "numeric",
    # games
    "DOOM": "multimedia", "Quake-III-Arena": "multimedia", "lab": "multimedia",
    # pointer / data structures
    "jemalloc": "pointer_data",
    # string / parsing / compilers
    "8cc": "string_parse", "c4": "string_parse", "bitwise": "string_parse",
    "jq": "string_parse", "mruby": "string_parse", "xLua": "string_parse",
    "skynet": "string_parse", "mjolnir": "string_parse",
    "capstone": "string_parse", "redcarpet": "string_parse",
    "radare2": "string_parse", "jerryscript": "string_parse",
    "yaf": "string_parse",
    # compression
    "brotli": "crypto", "borg": "crypto", "lz4": "crypto",
    "zstd": "crypto", "upx": "crypto", "oss-fuzz": "crypto",
    # systems / OS / embedded
    "linux": "systems", "darwin-xnu": "systems", "freebsd": "systems",
    "systemd": "systems", "fastsocket": "systems", "esp-idf": "systems",
    "i3": "systems", "sway": "systems", "tmux": "systems",
    "ish": "systems", "tini": "systems", "openwrt": "systems",
    "lede": "systems", "winfile": "systems", "reactos": "systems",
    "raspberry-pi-os": "systems", "os-tutorial": "systems",
    "qmk_firmware": "systems", "gb-studio": "systems",
    "arduino-esp32": "systems", "Arduino": "systems",
    "anypixel": "systems", "micropython": "systems",
    "macvim": "systems", "rofi": "systems", "htop": "systems",
    "nnn": "systems", "kilo": "systems", "robotjs": "systems",
    "robotgo": "systems", "streem": "systems",
    # networking
    "nginx": "systems", "nginx-rtmp-module": "systems",
    "http-parser": "systems", "h2o": "systems", "curl": "systems",
    "wrk": "systems", "japronto": "systems", "mongoose": "systems",
    "memcached": "systems", "hiredis": "systems", "redis": "systems",
    "twemproxy": "systems", "toxcore": "systems",
    "libevent": "systems", "libuv": "systems",
    "proxychains-ng": "systems", "goaccess": "systems",
    "nanomsg": "systems", "fastdfs": "systems", "kcp": "systems",
    "RetroArch": "systems", "lwan": "systems", "tengine": "systems",
    "SoftEtherVPN": "systems", "dsvpn": "systems", "openvpn": "systems",
    "masscan": "systems", "tg": "systems", "no-more-secrets": "systems",
    # databases / storage
    "db_tutorial": "systems", "postgres": "systems",
    "sqlcipher": "systems", "timescaledb": "systems",
    "TDengine": "systems", "ccv": "systems", "Craft": "systems",
    "poco": "systems", "nodemcu-firmware": "systems", "wcdb": "systems",
    "seafile": "systems", "ZipArchive": "systems",
    "phpredis": "systems", "beanstalkd": "systems",
    "rufus": "systems", "zfs": "systems",
    # general / misc
    "progress": "general", "stb": "multimedia",
    "glfw": "multimedia", "git": "systems", "tig": "systems",
    "libgit2": "systems",
}

# Класс по умолчанию для AnghaBench-проектов не в словаре
_ANGHA_DEFAULT_CLASS = "systems"


def get_benchmark_class(name: str) -> str:
    """Возвращает per-class домен для бенчмарка."""
    # 1. Прямое назначение
    if name in _INDIVIDUAL_CLASSES:
        return _INDIVIDUAL_CLASSES[name]

    # 2. AnghaBench — по проекту
    if name.startswith("anghabench__"):
        project = name.split("__")[1]
        return _ANGHA_PROJECT_CLASSES.get(project, _ANGHA_DEFAULT_CLASS)

    # 3. По набору (prefix до __)
    suite = name.split("__")[0]
    return _SUITE_CLASSES.get(suite, "general")
