/* =====================================
   MYVOICE VOTER BALLOT - PREMIUM ENTERPRISE JAVASCRIPT
   FR Ramon Kabuga Technical Secondary School
   2026 Enterprise Edition
   ===================================== */

// =====================================
// GLOBAL STATE MANAGEMENT
// =====================================

const BallotState = {
    currentPosition: 0,
    totalPositions: 0,
    completedPositions: new Set(),
    selectedCandidates: {},
    isSubmitting: false,
    sessionTimer: null,
    sessionTimeRemaining: 30 * 60,
    electionEndTime: null,
    announcementMessages: [],
    currentAnnouncementIndex: 0,
    celebrationActive: false,
    manifestoModalOpen: false
};

// =====================================
// INITIALIZATION
// =====================================

document.addEventListener('DOMContentLoaded', function() {
    const config = window.BallotConfig || {};
    
    initializeBallot(config);
    initializeSessionTimer();
    initializeParticleCanvas();
    initializeKeyboardNavigation();
    initializeAccessibility();
    initializeConnectionStatus();
    initializeAnnouncements();
});

function initializeBallot(config) {
    // Store configuration
    BallotState.totalPositions = config.totalPositions || 0;
    BallotState.electionEndTime = config.electionEnd || null;
    
    if (config.countdown) {
        startElectionCountdown(config.countdown);
    }
    
    // Update all positions as completed when navigated
    updateProgress();
    
    // Initialize candidate selection handlers
    initializeCandidateSelection();
    
    // Initialize vote submission
    initializeVoteSubmission();
    
    // Check if voter has already voted — trigger alarm + red announcement
    if (config.alreadyVoted) {
        setTimeout(() => {
            playAlarmSound();
            showDuplicateVoteWarning(
                "⚠️ SECURITY ALERT: You have already cast your vote in this election. " +
                "Duplicate voting is strictly prohibited and has been logged."
            );
        }, 300);
    }
    
    // Auto-scroll to first position
    if (BallotState.totalPositions > 0) {
        setTimeout(() => scrollToPosition(0), 300);
    }
}


// =====================================
// LIVE CLOCK & DATE
// =====================================

function initializeLiveClock() {
    function updateClock() {
        const now = new Date();
        const options = {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        };
        
        const dateElement = document.getElementById('live-date');
        const timeElement = document.getElementById('live-time');
        
        if (dateElement) {
            dateElement.textContent = now.toLocaleDateString('en-US', options);
        }
        
        if (timeElement) {
            timeElement.textContent = now.toLocaleTimeString('en-US', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        }
    }
    
    updateClock();
    setInterval(updateClock, 1000);
}

// Initialize live clock on load
if (typeof window.BallotConfig !== 'undefined') {
    initializeLiveClock();
}

// =====================================
// ELECTION COUNTDOWN TIMER
// =====================================

function startElectionCountdown(endTimeString) {
    const countdownElement = document.getElementById('countdown-timer');
    if (!countdownElement || !endTimeString) return;
    
    const endTime = new Date(endTimeString);
    if (isNaN(endTime.getTime())) return;
    
    function updateCountdown() {
        const now = new Date();
        const diff = endTime - now;
        
        if (diff <= 0) {
            countdownElement.innerHTML = '<span class="countdown-value" style="background: var(--color-crimson);">EXPIRED</span>';
            return;
        }
        
        const hours = Math.floor(diff / (1000 * 60 * 60));
        const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        const seconds = Math.floor((diff % (1000 * 60)) / 1000);
        
        document.getElementById('countdown-hours').textContent = String(hours).padStart(2, '0');
        document.getElementById('countdown-mins').textContent = String(minutes).padStart(2, '0');
        document.getElementById('countdown-secs').textContent = String(seconds).padStart(2, '0');
    }
    
    updateCountdown();
    setInterval(updateCountdown, 1000);
}

// =====================================
// SESSION TIMER
// =====================================

function initializeSessionTimer() {
    const timerElement = document.getElementById('session-timer');
    if (!timerElement) return;
    
    function updateTimerDisplay() {
        const minutes = Math.floor(BallotState.sessionTimeRemaining / 60);
        const seconds = BallotState.sessionTimeRemaining % 60;
        
        timerElement.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        
        // Color changes based on time remaining
        if (BallotState.sessionTimeRemaining < 180) {
            timerElement.style.color = '#DC2626';
            timerElement.style.animation = 'pulse 1s ease-in-out infinite';
        } else if (BallotState.sessionTimeRemaining < 300) {
            timerElement.style.color = '#F59E0B';
        } else {
            timerElement.style.color = '#10B981';
        }
    }
    
    updateTimerDisplay();
    
    BallotState.sessionTimer = setInterval(() => {
        BallotState.sessionTimeRemaining--;
        updateTimerDisplay();
        
        if (BallotState.sessionTimeRemaining <= 0) {
            handleSessionTimeout();
        }
    }, 1000);
}

function handleSessionTimeout() {
    clearInterval(BallotState.sessionTimer);
    showNotification('Your session has expired. Please log in again.', 'error');
    setTimeout(() => {
        window.location.href = '/voter/logout';
    }, 2000);
}

// =====================================
// CANDIDATE SELECTION
// =====================================

function initializeCandidateSelection() {
    document.querySelectorAll('.candidate-option').forEach(option => {
        const radio = option.querySelector('input[type="radio"]');
        const positionBtn = option.querySelector('.select-btn');
        
        if (!radio) return;
        
        radio.addEventListener('change', onCandidateSelect);
        
        // Handle individual candidate selection buttons
        if (positionBtn) {
            positionBtn.addEventListener('click', function(e) {
                e.preventDefault();
                radio.checked = true;
                radio.dispatchEvent(new Event('change', { bubbles: true }));
                
                // Scroll to close the card
                option.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            });
        }
    });
}

function onCandidateSelect(e) {
    const radio = e.target;
    const positionId = radio.name.replace('candidate_id_', '');
    const candidateCard = radio.closest('.candidate-option');
    
    // Remove selected from all in this position group
    document.querySelectorAll(`input[name="${radio.name}"]`).forEach(input => {
        const card = input.closest('.candidate-option');
        if (card) card.classList.remove('selected');
    });
    
    // Mark as selected
    candidateCard.classList.add('selected');
    
    // Update state
    if (candidateCard.querySelector('input[type="radio"]:checked')) {
        BallotState.selectedCandidates[positionId] = radio.value;
    } else {
        delete BallotState.selectedCandidates[positionId];
    }
    
    // Update progress
    updateProgress();
    
    // Play subtle sound
    playSound('select');
}

// =====================================
// PROGRESS TRACKING
// =====================================

function updateProgress() {
    const selectedCount = Object.keys(BallotState.selectedCandidates).length;
    const percentage = BallotState.totalPositions > 0 
        ? Math.round((selectedCount / BallotState.totalPositions) * 100) 
        : 0;
    
    // Update progress bar
    const progressBar = document.getElementById('progress-bar');
    if (progressBar) {
        progressBar.style.width = `${percentage}%`;
    }
    
    // Update progress text
    const progressCount = document.getElementById('progress-count');
    const progressPercent = document.getElementById('progress-percent');
    if (progressCount) {
        progressCount.textContent = `${selectedCount} / ${BallotState.totalPositions} Positions Completed`;
    }
    if (progressPercent) {
        progressPercent.textContent = `${percentage}%`;
    }
    
    // Update step indicators
    updateStepIndicators();
}

function updateStepIndicators() {
    const positionSections = document.querySelectorAll('.position-card');
    
    positionSections.forEach((section, index) => {
        const indicator = section.querySelector('.step-indicator');
        if (!indicator) return;
        
        const positionId = section.dataset.positionId;
        const positionNum = section.querySelector('.position-number');
        
        if (BallotState.completedPositions.has(positionId)) {
            indicator.innerHTML = '✓';
            indicator.className = 'step-indicator completed';
            if (positionNum) positionNum.style.background = 'var(--color-success)';
        } else if (BallotState.selectedCandidates[positionId]) {
            indicator.innerHTML = '🟡';
            indicator.className = 'step-indicator current';
            if (positionNum) positionNum.style.background = 'var(--color-primary-gradient)';
        } else {
            indicator.innerHTML = '⚪';
            indicator.className = 'step-indicator remaining';
            if (positionNum) positionNum.style.background = 'var(--color-primary-gradient)';
        }
    });
}

// =====================================
// VOTE SUBMISSION
// =====================================

function initializeVoteSubmission() {
    const submitButton = document.getElementById('submit-vote-btn');
    if (!submitButton) return;
    
    submitButton.addEventListener('click', function(e) {
        e.preventDefault();
        handleSubmitVote();
    });
}

async function handleSubmitVote() {
    if (BallotState.isSubmitting) return;
    
    // Validate selections
    const missingPositions = [];
    for (let i = 0; i < BallotState.totalPositions; i++) {
        const section = document.querySelector(`.position-card[data-position-id]`);
        const positionId = section ? section.dataset.positionId : null;
        
        if (positionId && !BallotState.selectedCandidates[positionId]) {
            const positionHeader = section.querySelector('.position-name');
            missingPositions.push(positionHeader ? positionHeader.textContent : 'Position ' + (i + 1));
        }
    }
    
    if (missingPositions.length > 0) {
        showNotification(`Please select candidates for: ${missingPositions.join(', ')}`, 'warning');
        return;
    }
    
    // Submit vote
    BallotState.isSubmitting = true;
    const submitBtn = document.getElementById('submit-vote-btn');
    
    if (submitBtn) {
        submitBtn.classList.add('loading');
        submitBtn.disabled = true;
    }
    
    try {
        const formData = new FormData(document.getElementById('votingForm'));
        
        const response = await fetch('/voter/submit-vote', {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-HTTP-Request-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showCelebration();
            setTimeout(() => showSuccessModal(result), 500);
        } else if (result.duplicate_vote) {
            playAlarmSound();
            showDuplicateVoteWarning(result.message);
        } else {
            showNotification(result.message || 'Failed to submit vote', 'error');
        }

    } catch (error) {
        console.error('Vote submission error:', error);
        showNotification('Network error. Please check your connection and try again.', 'error');
    } finally {
        if (submitBtn) {
            submitBtn.classList.remove('loading');
            submitBtn.disabled = false;
        }
        BallotState.isSubmitting = false;
    }
}

// =====================================
// SUCCESS MODAL
// =====================================

function showSuccessModal(result) {
    const modal = document.getElementById('success-modal');
    if (!modal) return;
    
    modal.classList.add('active');
    
    // Update modal content
    const messageEl = modal.querySelector('#modal-message');
    if (messageEl) {
        messageEl.textContent = 'Your vote has been securely encrypted and stored. Preparing next position...';
    }
    
    // Start countdown
    let count = 5;
    const countdownEl = document.getElementById('countdown-num');
    
    const countdownInterval = setInterval(() => {
        count--;
        countdownEl.textContent = count;
        
        if (count <= 0) {
            clearInterval(countdownInterval);
            closeModal('success-modal');
            
            // Mark position as completed
            markPositionCompleted();
        }
    }, 1000);
}

function markPositionCompleted() {
    if (BallotState.completedPositions.size < BallotState.totalPositions) {
        // Scroll to next position
        const nextPosition = BallotState.completedPositions.size;
        scrollToPosition(nextPosition);
    } else {
        // All positions completed - show final modal
        showFinalModal();
    }
}

// =====================================
// FINAL CONFIRMATION MODAL
// =====================================

function showFinalModal() {
    const modal = document.getElementById('final-modal');
    if (!modal) return;
    
    modal.classList.add('active');
    
    // Start celebration
    startFinalCelebration();
    
    // Auto logout after 5 seconds
    setTimeout(() => {
        setTimeout(() => {
            window.location.href = '/voter/logout';
        }, 1000);
    }, 5000);
}

// =====================================
// PETALS & PARTICLES CELEBRATION
// =====================================

function startFinalCelebration() {
    const petalsContainer = document.getElementById('petals-container');
    if (!petalsContainer) return;
    
    // Create 30 petals
    for (let i = 0; i < 30; i++) {
        setTimeout(() => {
            const petal = document.createElement('div');
            petal.className = 'petal';
            petal.style.left = `${Math.random() * 100}%`;
            petal.style.animationDuration = `${1 + Math.random() * 2}s`;
            petal.style.animationDelay = `${Math.random() * 0.5}s`;
            petalsContainer.appendChild(petal);
            
            setTimeout(() => {
                petal.remove();
            }, 3000);
        }, i * 100);
    }
}

function showCelebration() {
    BallotState.celebrationActive = true;
    
    const container = document.createElement('div');
    container.id = 'celebration-container';
    container.className = 'celebration-container';
    document.body.appendChild(container);
    
    // Create particles using emojis
    const particleTypes = ['🌸', '🎉', '✨', '🎊', '💫', '⭐', '🌟', '💐'];
    const colors = ['#2563EB', '#10B981', '#F59E0B', '#DC2626', '#8B5CF6'];
    
    for (let i = 0; i < 80; i++) {
        setTimeout(() => {
            createParticle(container, particleTypes, colors);
        }, i * 30);
    }
    
    // Stop after 5 seconds
    setTimeout(() => {
        stopCelebration();
    }, 5000);
}

function createParticle(container, types, colors) {
    const particle = document.createElement('div');
    particle.className = 'particle';
    
    const type = types[Math.floor(Math.random() * types.length)];
    const isEmoji = type.length > 1;
    
    if (isEmoji) {
        particle.textContent = type;
        particle.style.fontSize = `${Math.random() * 24 + 20}px`;
    } else {
        particle.style.width = `${Math.random() * 10 + 5}px`;
        particle.style.height = `${Math.random() * 10 + 5}px`;
        particle.style.background = colors[Math.floor(Math.random() * colors.length)];
        particle.style.borderRadius = Math.random() > 0.5 ? '50%' : '0';
    }
    
    particle.style.left = `${Math.random() * 100}%`;
    particle.style.animationDuration = `${Math.random() * 3 + 4}s`;
    particle.style.animationDelay = `${Math.random() * 2}s`;
    
    container.appendChild(particle);
    
    setTimeout(() => {
        particle.remove();
    }, 7000);
}

function stopCelebration() {
    BallotState.celebrationActive = false;
    const container = document.getElementById('celebration-container');
    if (container) {
        container.remove();
    }
}

// =====================================
// PARTICLE CANVAS BACKGROUND
// =====================================

function initializeParticleCanvas() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;
    
    const canvas = document.createElement('canvas');
    canvas.id = 'particle-canvas';
    canvas.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: -1;
        opacity: 0.15;
    `;
    document.body.insertBefore(canvas, document.body.firstChild);
    
    const ctx = canvas.getContext('2d');
    let particles = [];
    
    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        initParticles();
    }
    
    function createParticle() {
        return {
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
            size: Math.random() * 2 + 0.5,
            speedX: (Math.random() - 0.5) * 0.3,
            speedY: (Math.random() - 0.5) * 0.3,
            opacity: Math.random() * 0.3 + 0.1,
            color: `hsl(${Math.floor(Math.random() * 60 + 200)}, ${Math.floor(Math.random() * 30 + 50)}%, ${Math.floor(Math.random() * 30 + 60)}%)`
        };
    }
    
    function initParticles() {
        particles = [];
        const count = Math.min(70, Math.floor((canvas.width * canvas.height) / 10000));
        for (let i = 0; i < count; i++) {
            particles.push(createParticle());
        }
    }
    
    function animate() {
        if (!document.getElementById('particle-canvas')) return;
        
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        particles.forEach(particle => {
            particle.x += particle.speedX;
            particle.y += particle.speedY;
            
            // Wrap around
            if (particle.x < 0) particle.x = canvas.width;
            if (particle.x > canvas.width) particle.x = 0;
            if (particle.y < 0) particle.y = canvas.height;
            if (particle.y > canvas.height) particle.y = 0;
            
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            ctx.fillStyle = particle.color + particle.opacity.toString();
            ctx.fill();
        });
        
        requestAnimationFrame(animate);
    }
    
    resize();
    animate();
    
    window.addEventListener('resize', resize);
}

// =====================================
// MODAL SYSTEM
// =====================================

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        setTimeout(() => {
            modal.remove();
        }, 300);
    }
}

function openManifestoModal(candidateName, manifesto) {
    if (BallotState.manifestoModalOpen) return;
    BallotState.manifestoModalOpen = true;
    
    const modal = document.getElementById('manifesto-modal');
    const title = modal.querySelector('#manifesto-title');
    const body = modal.querySelector('#manifesto-body');
    
    if (modal && title && body) {
        title.textContent = `${candidateName}'s Full Statement`;
        body.innerHTML = `<p style="line-height: 1.6; color: var(--color-secondary);">${manifesto}</p>`;
        modal.classList.add('active');
    }
}

function closeManifestoModal() {
    BallotState.manifestoModalOpen = false;
    const modal = document.getElementById('manifesto-modal');
    if (modal) {
        modal.classList.remove('active');
        setTimeout(() => modal.remove(), 300);
    }
}

// Close modals on ESC key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeModal('success-modal');
        closeModal('final-modal');
        closeManifestoModal();
    }
});

// =====================================
// ANNOUNCEMENTS
// =====================================

function initializeAnnouncements() {
    const marquee = document.getElementById('announcement-marquee');
    if (!marquee) return;
    
    const messages = [
        "📢 Election voting is now open! Cast your vote by the deadline.",
        "🔒 Your vote is secure and confidential. Thank you for participating in democracy!",
        "⏰ Remember: Each student can only vote once per position.",
        "✅ Voting complete? Check your dashboard for confirmation."
    ];
    
    if (messages.length > 0) {
        marquee.innerHTML = messages.map(msg => `<span class="announcement-item">${msg}</span>`).join(' ');
    }
}

// =====================================
// CONNECTION STATUS
// =====================================

function initializeConnectionStatus() {
    const statusElement = document.getElementById('connection-status');
    if (!statusElement) return;
    
    function updateStatus() {
        if (navigator.onLine) {
            statusElement.innerHTML = '🟢 Connected';
            statusElement.style.color = '#10B981';
        } else {
            statusElement.innerHTML = '🔴 Offline';
            statusElement.style.color = '#DC2626';
        }
    }
    
    window.addEventListener('online', updateStatus);
    window.addEventListener('offline', updateStatus);
    updateStatus();
}

// =====================================
// KEYBOARD NAVIGATION
// =====================================

function initializeKeyboardNavigation() {
    document.addEventListener('keydown', function(e) {
        // ESC to close modals
        if (e.key === 'Escape') {
            closeModal('success-modal');
            closeModal('final-modal');
            closeManifestoModal();
        }
        
        // Ctrl/Cmd + Enter to submit
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            const submitBtn = document.getElementById('submit-vote-btn');
            if (submitBtn && !submitBtn.disabled) {
                handleSubmitVote();
            }
        }
        
        // Arrow keys for navigation (with Alt)
        if (e.altKey) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                const nextPosition = Math.min(BallotState.currentPosition + 1, BallotState.totalPositions - 1);
                scrollToPosition(nextPosition);
                BallotState.currentPosition = nextPosition;
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                const prevPosition = Math.max(BallotState.currentPosition - 1, 0);
                scrollToPosition(prevPosition);
                BallotState.currentPosition = prevPosition;
            }
        }
    });
}

// =====================================
// POSITION NAVIGATION
// =====================================

function scrollToPosition(index) {
    if (index < 0 || index >= BallotState.totalPositions) return;
    
    BallotState.currentPosition = index;
    
    const section = document.querySelector(`.position-card[data-position-id]`);
    if (section) {
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        section.focus();
    }
}

// =====================================
// ACCESSIBILITY
// =====================================

function initializeAccessibility() {
    // ARIA labels for candidate cards
    document.querySelectorAll('.candidate-option').forEach((option, index) => {
        const radio = option.querySelector('input[type="radio"]');
        if (radio) {
            radio.setAttribute('aria-label', `Select candidate ${index + 1}`);
        }
        
        // Keyboard navigation for candidate cards
        option.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                const radio = option.querySelector('input[type="radio"]');
                if (radio) {
                    radio.checked = true;
                    radio.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
        });
    });
    
    // Live region for announcements
    const liveRegion = document.createElement('div');
    liveRegion.setAttribute('aria-live', 'polite');
    liveRegion.setAttribute('aria-atomic', 'true');
    liveRegion.className = 'sr-only';
    liveRegion.id = 'live-region';
    document.body.appendChild(liveRegion);
}

function announceToScreenReader(message) {
    const liveRegion = document.getElementById('live-region');
    if (liveRegion) {
        liveRegion.textContent = message;
    }
}

// =====================================
// NOTIFICATIONS
// =====================================

function showNotification(message, type = 'info') {
    // Check if toast container exists
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️'
    };
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
        <div class="toast-message">${message}</div>
        <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    
    container.appendChild(toast);
    
    // Auto-dismiss
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
    
    // Announce to screen readers
    announceToScreenReader(`${type}: ${message}`);
}

// =====================================
// SOUND EFFECTS
// =====================================

function playSound(type) {
    if (!localStorage.getItem('soundsEnabled') && localStorage.getItem('soundsEnabled') !== 'false') {
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            
            const frequencies = {
                select: 800,
                success: [600, 800],
                error: 300,
                navigation: 500
            };
            
            if (type === 'success' || type === 'select') {
                oscillator.frequency.value = frequencies[type];
                gainNode.gain.value = 0.08;
                oscillator.start();
                oscillator.stop(audioContext.currentTime + 0.1);
            }
        } catch (e) {
            // Audio context not supported
        }
    }
}

// =====================================
// ALARM SOUND & DUPLICATE VOTE WARNING
// =====================================

function playAlarmSound() {
    // Try playing the dedicated alarm audio element first
    const alarmAudio = document.getElementById('alarm-sound');
    if (alarmAudio) {
        alarmAudio.volume = 0.9;
        alarmAudio.currentTime = 0;
        alarmAudio.play().catch(e => {
            // Fallback to Web Audio API if audio element fails
            playAlarmFallback();
        });
        // Loop the alarm for attention
        alarmAudio.onended = function() {
            if (document.getElementById('duplicate-vote-banner') && 
                document.getElementById('duplicate-vote-banner').classList.contains('active')) {
                alarmAudio.currentTime = 0;
                alarmAudio.play().catch(() => {});
            }
        };
    } else {
        playAlarmFallback();
    }
}

function playAlarmFallback() {
    // Web Audio API fallback: generate a loud siren alarm
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        if (!audioContext) return;

        let isPlaying = true;
        let currentFreq = 880;

        function playAlarmCycle() {
            if (!isPlaying) return;

            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);

            oscillator.frequency.value = currentFreq;
            gainNode.gain.value = 0.3;

            oscillator.start();
            oscillator.stop(audioContext.currentTime + 0.3);

            // Alternate frequency for siren effect
            currentFreq = currentFreq === 880 ? 440 : 880;

            setTimeout(playAlarmCycle, 350);
        }

        playAlarmCycle();

        // Stop after 5 seconds
        setTimeout(() => {
            isPlaying = false;
        }, 5000);
    } catch (e) {
        console.warn('Alarm sound could not be played:', e);
    }
}

function showDuplicateVoteWarning(message) {
    const banner = document.getElementById('duplicate-vote-banner');
    if (!banner) return;

    showAlarmSound();

    // Show the red banner
    banner.classList.add('active');

    // Update the announcement marquee with a warning
    const marquee = document.getElementById('announcement-marquee');
    if (marquee) {
        marquee.innerHTML = '<span class="announcement-item" style="color: var(--color-white); font-weight: 700;">🚨 SECURITY ALERT: Duplicate vote attempt detected and blocked. Each voter may vote only once.</span>';
        marquee.style.animation = 'marquee 10s linear infinite';
    }

    // Disable the submit button
    const submitBtn = document.getElementById('submit-vote-btn');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.classList.add('blocked');
    }

    // Announce to screen readers with urgency
    announceToScreenReader('🚨 SECURITY ALERT: Duplicate vote attempt blocked. ' + message, true);

    // Close button handler
    const closeBtn = document.getElementById('banner-close');
    if (closeBtn) {
        closeBtn.onclick = function() {
            banner.classList.remove('active');
            // Restore marquee
            if (marquee) {
                marquee.innerHTML = '';
                initializeAnnouncements();
            }
            // Re-enable submit button
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.classList.remove('blocked');
            }
        };
    }
}

// =====================================
// UTILITY FUNCTIONS
// =====================================

function debounce(func, wait = 300) {

    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

function throttle(func, limit = 100) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

function formatNumber(num) {
    return new Intl.NumberFormat('en-US').format(num);
}

function getViewportHeight() {
    return Math.max(
        document.documentElement.clientHeight,
        window.innerHeight || 0
    );
}

// =====================================
// EXPANDABLE MANIFESTO
// =====================================

document.querySelectorAll('.expand-btn').forEach(btn => {
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        const candidateCard = this.closest('.candidate-option');
        const fullText = this.getAttribute('data-full-text') || '';
        const candidateName = candidateCard.querySelector('.candidate-name')?.textContent;
        
        if (fullText) {
            openManifestoModal(candidateName || 'Candidate', fullText);
        }
    });
});

// =====================================
// QUICK CANDIDATE SELECTOR
// =====================================

document.querySelectorAll('.quick-candidate-item').forEach(item => {
    item.addEventListener('click', function(e) {
        e.preventDefault();
        const positionId = this.getAttribute('data-position');
        const candidateId = this.getAttribute('data-candidate');
        
        if (positionId && candidateId) {
            // Find and check the corresponding radio button
            const radio = document.querySelector(`input[name="candidate_id_${positionId}"][value="${candidateId}"]`);
            if (radio) {
                // Uncheck all other radios in the same group
                document.querySelectorAll(`input[name="candidate_id_${positionId}"]`).forEach(r => {
                    r.closest('.candidate-option').classList.remove('selected');
                });
                
                // Check the selected radio
                radio.checked = true;
                radio.dispatchEvent(new Event('change', { bubbles: true }));
                
                // Add selected class to the card
                radio.closest('.candidate-option').classList.add('selected');
                
                // Scroll to the candidate card
                const cardElement = document.querySelector(`[data-candidate-id="${candidateId}"]`) || radio.closest('.candidate-card-inner');
                if (cardElement) {
                    cardElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                
                // Show notification
                showNotification(`Selected candidate. Ready to submit your vote.`, 'success');
            }
        }
    });
});

// =====================================
// FINAL INITIALIZATION
// =====================================

// Initialize live clock if config exists
if (window.BallotConfig) {
    initializeLiveClock();
}

// Export for global access
window.BallotState = BallotState;
window.closeModal = closeModal;
window.closeManifestoModal = closeManifestoModal;
window.showNotification = showNotification;
window.handleSubmitVote = handleSubmitVote;
window.playAlarmSound = playAlarmSound;
window.showDuplicateVoteWarning = showDuplicateVoteWarning;

