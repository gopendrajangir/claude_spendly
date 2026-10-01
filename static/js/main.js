// main.js — students will add JavaScript here as features are built

// ------------------------------------------------------------------ //
// Landing page: "See how it works" video modal                        //
// ------------------------------------------------------------------ //

(function () {
    var openBtn = document.getElementById('how-it-works-btn');
    var modal = document.getElementById('video-modal');
    var closeBtn = document.getElementById('video-modal-close');
    var frame = document.getElementById('video-frame');

    if (!openBtn || !modal || !closeBtn || !frame) return;

    function openModal() {
        // Set src only on open so the video loads and plays on demand
        frame.src = frame.dataset.src;
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
        closeBtn.focus();
    }

    function closeModal() {
        modal.hidden = true;
        // Clearing src unloads the player, which stops playback
        frame.src = '';
        document.body.style.overflow = '';
        openBtn.focus();
    }

    openBtn.addEventListener('click', openModal);
    closeBtn.addEventListener('click', closeModal);

    // Click on the dark overlay (but not the modal content) closes it
    modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !modal.hidden) closeModal();
    });
})();
