/* =====================================
   MyVoice — Professional Homepage JS
   ===================================== */

(function () {
    "use strict";

    // =====================================
    // Configuration
    // =====================================

    var HOMEPAGE = {
        // Default hero images (local fallback)
        defaultImages: [
            "/static/images/homepage/image-01.jpg",
            "/static/images/homepage/image-02.jpg",
            "/static/images/homepage/image-03.jpg",
            "/static/images/homepage/image-04.jpg",
            "/static/images/homepage/image-05.jpg",
            "/static/images/homepage/image-06.jpg",
        ],

        // Primary fallback image (always used if everything else fails)
        primaryFallback: "/static/images/homepage/image-01.jpg",

        // Rotation timing
        rotationInterval: 6000,
        fadeDuration: 800,

        // Preload queue limit
        preloadLimit: 3,
    };

    // =====================================
    // State
    // =====================================

    var state = {
        currentImageIndex: 0,
        isRotating: false,
        intervalId: null,
        prefersReducedMotion: false,
        images: [],
        slides: [],
        slideCount: 0,
        loadedImages: new Set(),
        errorCount: 0,
    };

    // =====================================
    // Utilities
    // =====================================

    var utils = {
        rand: function (min, max) {
            return Math.floor(Math.random() * (max - min + 1)) + min;
        },

        prefersReducedMotion: function () {
            return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        },

        isOnlineImage: function (url) {
            return url && (url.startsWith("http://") || url.startsWith("https://"));
        },

        loadImage: function (src, timeoutMs) {
            var timeout = timeoutMs || 5000;
            return new Promise(function (resolve, reject) {
                var img = new Image();
                var timer = setTimeout(function () {
                    img.onload = null;
                    img.onerror = null;
                    reject(new Error("Timeout loading image: " + src));
                }, timeout);

                img.onload = function () {
                    clearTimeout(timer);
                    resolve(src);
                };

                img.onerror = function () {
                    clearTimeout(timer);
                    reject(new Error("Failed to load image: " + src));
                };

                img.src = src;
            });
        },

        getStoredTheme: function () {
            try {
                return localStorage.getItem("mv-theme") || null;
            } catch (e) {
                return null;
            }
        },

        setTheme: function (theme) {
            document.documentElement.setAttribute("data-mv-theme", theme);
            try {
                localStorage.setItem("mv-theme", theme);
            } catch (e) {}
        },

        initTheme: function () {
            var stored = this.getStoredTheme();
            if (stored === "dark") {
                document.documentElement.setAttribute("data-mv-theme", "dark");
            } else if (stored === "light") {
                document.documentElement.setAttribute("data-mv-theme", "light");
            }
        },

        toggleTheme: function () {
            var current = document.documentElement.getAttribute("data-mv-theme");
            var newTheme = current === "dark" ? "light" : "dark";
            this.setTheme(newTheme);
            return newTheme;
        },

        smoothScrollTo: function (targetId) {
            var target = document.getElementById(targetId);
            if (target) {
                var offset = target.offsetTop;
                var start = window.pageYOffset || document.documentElement.scrollTop;
                var distance = offset - start - 80;
                var duration = 600;
                var startTime = null;

                function animation(currentTime) {
                    if (!startTime) startTime =.currentTime;
                    var progress = currentTime - startTime;
                    var percent = Math.min(progress / duration, 1);

                    var ease = percent < 0.5
                        ? 2 * percent * percent
                        : -1 + (4 - 2 * percent) * percent;

                    window.scrollTo(0, start + distance * ease);

                    if (progress < duration) {
                        requestAnimationFrame(animation);
                    }
                }

                if (distance !== 0) {
                    requestAnimationFrame(animation);
                }
            }
        },
    };

    // =====================================
    // Image Manager — dynamic hero images
    // =====================================

    var imageManager = {
        init: function () {
            state.prefersReducedMotion = utils.prefersReducedMotion();

            var slides = document.querySelectorAll(".hero-image-slide");
            if (!slides || slides.length === 0) {
                this.showFallback();
                return;
            }

            state.slides = slides;
            state.slideCount = slides.length;

            // Build effective image list: online images first, local fallbacks after
            this.buildImageList();

            // Pick a random starting image for session variety
            var startIdx = utils.rand(0, state.slideCount - 1);
            state.currentImageIndex = startIdx;

            // Preload adjacent images
            this.preloadAdjacent();

            // Show the starting slide
            this.showSlide(startIdx, false);

            // Start rotation if more than one image and no reduced motion
            if (state.slideCount > 1 && !state.prefersReducedMotion) {
                this.startRotation();
            }
        },

        buildImageList: function () {
            // The Jinja template already creates slides for configured images.
            // This method validates online URLs and swaps in fallback on failure.
            var slides = state.slides;
            for (var i = 0; i < slides.length; i++) {
                var img = slides[i].querySelector("img");
                if (img) {
                    var url = img.getAttribute("data-src") || img.getAttribute("src") || "";
                    state.images.push(url);
                    img.setAttribute("data-original-src", url);
                }
            }
        },

        showFallback: function () {
            var wrapper = document.querySelector(".hero-image-wrapper");
            if (wrapper) {
                wrapper.innerHTML =
                    '<div class="hero-fallback">' +
                    '<div>Every Vote Counts</div>' +
                    '</div>';
            }
        },

        showSlide: function (index, animate) {
            var animateOpt = animate !== undefined ? animate : true;

            for (var i = 0; i < state.slideCount; i++) {
                state.slides[i].classList.remove("active");
            }

            var slide = state.slides[index];
            if (slide) {
                if (animateOpt && !state.prefersReducedMotion) {
                    slide.style.transition = "opacity 0.8s ease, transform 0.8s ease";
                } else {
                    slide.style.transition = "none";
                }
                slide.classList.add("active");
            }

            state.currentImageIndex = index;

            // Try to preload next-next image in background
            var nextNext = (index + 2) % state.slideCount;
            this.preloadImage(nextNext);
        },

        nextSlide: function () {
            var next = state.currentImageIndex + 1;
            if (next >= state.slideCount) {
                next = 0;
            }
            this.showSlide(next, true);
        },

        preloadAdjacent: function () {
            var prev = (state.currentImageIndex - 1 + state.slideCount) % state.slideCount;
            var next = (state.currentImageIndex + 1) % state.slideCount;
            this.preloadImage(prev);
            this.preloadImage(next);
        },

        preloadImage: function (index) {
            if (index < 0 || index >= state.slideCount) return;
            if (state.loadedImages.has(index)) return;

            var img = state.slides[index].querySelector("img");
            if (img) {
                var url = img.getAttribute("data-original-src") || img.getAttribute("src");
                if (url && !state.loadedImages.has(index)) {
                    var preloadImg = new Image();
                    preloadImg.onload = function () {
                        state.loadedImages.add(index);
                    };
                    preloadImg.onerror = function () {
                        state.loadedImages.add(index);
                        // Swap to fallback
                        img.setAttribute("src", HOMEPAGE.primaryFallback);
                    };
                    preloadImg.src = url;
                    state.loadedImages.add(index);
                }
            }
        },

        startRotation: function () {
            if (state.intervalId) {
                clearInterval(state.intervalId);
            }

            state.isRotating = true;
            state.intervalId = setInterval(function () {
                if (document.visibilityState === "visible") {
                    imageManager.nextSlide();
                }
            }, HOMEPAGE.rotationInterval);
        },

        stopRotation: function () {
            state.isRotating = false;
            if (state.intervalId) {
                clearInterval(state.intervalId);
                state.intervalId = null;
            }
        },
    };

    // =====================================
    // Navigation
    // =====================================

    var navigation = {
        init: function () {
            this.bindSmoothScroll();
            this.bindMenuToggle();
            this.bindThemeToggle();
            this.bindContactLinks();
        },

        bindSmoothScroll: function () {
            var links = document.querySelectorAll("a[href^='#']");
            for (var i = 0; i < links.length; i++) {
                links[i].addEventListener("click", function (e) {
                    var href = this.getAttribute("href");
                    if (href && href.length > 1) {
                        var targetId = href.substring(1);
                        var target = document.getElementById(targetId);
                        if (target) {
                            e.preventDefault();
                            utils.smoothScrollTo(targetId);
                        }
                    }
                });
            }
        },

        bindMenuToggle: function () {
            var toggle = document.querySelector(".menu-toggle");
            var navLinks = document.querySelector(".nav-links");
            if (toggle && navLinks) {
                toggle.addEventListener("click", function () {
                    navLinks.classList.toggle("show");
                });
            }
        },

        bindThemeToggle: function () {
            var toggle = document.getElementById("themeToggle");
            if (toggle) {
                toggle.addEventListener("click", function () {
                    utils.toggleTheme();
                });
            }
        },

        bindContactLinks: function () {
            // Contact links are rendered as proper mailto/tel/wa links in the template
            // No additional JS needed — they work natively
        },
    };

    // =====================================
    // Contact Form
    // =====================================

    var contactForm = {
        init: function () {
            var form = document.getElementById("contactForm");
            if (!form) return;

            form.addEventListener("submit", function (e) {
                e.preventDefault();

                var name = form.querySelector("[name='name']").value.trim();
                var email = form.querySelector("[name='email']").value.trim();
                var message = form.querySelector("[name='message']").value.trim();

                if (!name || !email || !message) {
                    alert("Please fill in all fields.");
                    return;
                }

                // Use mailto as fallback for contact form submissions
                var subject = encodeURIComponent("MyVoice Contact Form Submission");
                var body = encodeURIComponent(
                    "Name: " + name + "\n" +
                    "Email: " + email + "\n\n" +
                    "Message:\n" + message
                );

                window.location.href = "mailto:mbonyimanagervais@gmail.com?subject=" + subject + "&body=" + body;
            });
        },
    };

    // =====================================
    // Page Visibility — pause rotation when hidden
    // =====================================

    var visibilityHandler = function () {
        if (document.hidden && state.isRotating) {
            imageManager.stopRotation();
        } else if (!document.hidden && !state.isRotating && state.slideCount > 1) {
            imageManager.startRotation();
        }
    };

    // =====================================
    // Initialize
    // =====================================

    function init() {
        utils.initTheme();
        navigation.init();
        contactForm.init();

        if (typeof document !== "undefined") {
            if (document.readyState === "loading") {
                document.addEventListener("DOMContentLoaded", function () {
                    imageManager.init();
                });
            } else {
                imageManager.init();
            }
        }

        document.addEventListener("visibilitychange", visibilityHandler);
    }

    init();
})();
