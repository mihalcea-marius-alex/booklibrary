document.addEventListener("DOMContentLoaded", function () {
    const adaptedCheckbox = document.querySelector('input[name="adapted"]');
    const filmTitleRow = document.querySelector('.form-row.field-film_title');
    const filmTitleInput = document.querySelector('input[name="film_title"]');
    const isbnRow = document.querySelector('.form-row.field-isbn');
    const coverRow = document.querySelector('.form-row.field-cover');
    let previewRow = document.querySelector('.form-row.field-cover_preview');
    const coverInput = document.querySelector('input[name="cover"]');

    const addRow = document.querySelector(".add-row");

    function toggleAddRow() {
        if (!addRow) return;

        const authorSelects = document.querySelectorAll("select[name^='bookauthor_set'][name$='-author']");
        let hasAuthor = false;
        authorSelects.forEach(select => {
            if (select.value) hasAuthor = true;
        });

        addRow.style.display = hasAuthor ? "table-row" : "none";
    }

    toggleAddRow();

    const observer = new MutationObserver(toggleAddRow);
    const authorContainer = document.querySelector("tbody");
    if (authorContainer) observer.observe(authorContainer, { childList: true, subtree: true });

    document.querySelectorAll("select[name^='bookauthor_set'][name$='-author']").forEach(select => {
        select.addEventListener("change", toggleAddRow);
    });

    function createPreviewRow() {
        const wrapper = document.createElement('div');
        wrapper.className = 'form-row field-cover_preview';

        const inner = document.createElement('div');
        const container = document.createElement('div');
        container.className = 'flex-container';

        const labelDiv = document.createElement('label');
        labelDiv.textContent = 'Cover Preview:';
        container.appendChild(labelDiv);

        const readonlyDiv = document.createElement('div');
        readonlyDiv.className = 'readonly';
        container.appendChild(readonlyDiv);

        inner.appendChild(container);
        wrapper.appendChild(inner);
        return wrapper;
    }

    function ensurePreviewRow() {
        if (!previewRow) {
            previewRow = createPreviewRow();
            if (coverRow && coverRow.parentNode) {
                coverRow.parentNode.insertBefore(previewRow, coverRow.nextSibling);
            } else {
                const form = document.querySelector('form');
                if (form) form.appendChild(previewRow);
            }
        }
    }

    function getServerPreviewUrl() {
        if (!previewRow) return null;
        const img = previewRow.querySelector('img');
        if (img && img.src) return img.src.trim();
        const a = previewRow.querySelector('a');
        if (a && a.href) return a.href.trim();
        const rd = previewRow.querySelector('.readonly');
        if (rd) {
            const txt = rd.textContent.trim();
            if (txt && txt !== '-' && txt.toLowerCase() !== 'none') {
                return txt;
            }
        }
        return null;
    }

    function clearPreviewContents() {
        ensurePreviewRow();
        const label = previewRow.querySelector('label');

        while (label && label.nextSibling) {
            label.parentNode.removeChild(label.nextSibling);
        }

        const rd = document.createElement('div');
        rd.className = 'readonly';
        rd.textContent = '';
        label.parentNode.appendChild(rd);
    }

    function setPreviewImage(url, isLocalPreview) {
        ensurePreviewRow();
        const label = previewRow.querySelector('label');

        while (label && label.nextSibling) {
            label.parentNode.removeChild(label.nextSibling);
        }

        const targetContainer = label.parentNode;

        const img = document.createElement('img');
        img.src = url;
        img.style.height = '150px';
        img.style.marginTop = '5px';
        img.alt = 'Cover preview';

        if (isLocalPreview) {
            targetContainer.appendChild(img);
        } else {
            const a = document.createElement('a');
            a.href = url;
            a.target = '_blank';
            a.appendChild(img);
            targetContainer.appendChild(a);
        }
    }

    function hidePreviewRow() {
        if (!previewRow) return;
        previewRow.style.display = 'none';
    }

    function showPreviewRow() {
        ensurePreviewRow();
        previewRow.style.display = '';
    }

    function isServerUrl(url) {
        if (!url) return false;
        return /^\/|^https?:\/\//i.test(url);
    }

    function updatePreviewVisibility() {
        if (!previewRow) previewRow = document.querySelector('.form-row.field-cover_preview');

        const serverUrl = getServerPreviewUrl();
        if (serverUrl && isServerUrl(serverUrl)) {
            setPreviewImage(serverUrl, false);
            showPreviewRow();
            return;
        }

        if (coverInput && coverInput.files && coverInput.files.length > 0) {
            const file = coverInput.files[0];
            if (file && file.type.indexOf('image') !== -1) {
                const reader = new FileReader();
                reader.onload = function (e) {
                    setPreviewImage(e.target.result, true);
                    showPreviewRow();
                };
                reader.readAsDataURL(file);
            } else {
                clearPreviewContents();
                hidePreviewRow();
            }
            return;
        }

        if (previewRow) {
            clearPreviewContents();
            hidePreviewRow();
        }
    }

    updatePreviewVisibility();
    setTimeout(updatePreviewVisibility, 300);

    if (coverInput) {
        coverInput.addEventListener('change', function () {
            updatePreviewVisibility();
        });
    }

    const form = document.querySelector('form');
    if (form) {
        const mo = new MutationObserver(function () {
            updatePreviewVisibility();
        });
        mo.observe(form, { childList: true, subtree: true });
        setTimeout(() => mo.disconnect(), 5000);
    }

    if (adaptedCheckbox && filmTitleInput && filmTitleRow) {
        function toggleFilmTitle() {
            if (!adaptedCheckbox.checked) {
                filmTitleInput.value = "";
                filmTitleRow.style.display = "none";
            } else {
                filmTitleRow.style.display = "";
            }
        }
        toggleFilmTitle();
        adaptedCheckbox.addEventListener("change", toggleFilmTitle);
    }

    function toggleIsbn() {
        if (!isbnRow) return;

        const isbnInput = isbnRow.querySelector('input[name="isbn"]');
        const isbnReadonlyDiv = isbnRow.querySelector('.readonly');
        let isbnValue = "";

        if (isbnInput) isbnValue = isbnInput.value.trim();
        else if (isbnReadonlyDiv) isbnValue = isbnReadonlyDiv.textContent.trim();

        if (!isbnValue || isbnValue === "-" || isbnValue === "—") {
            isbnRow.style.display = "none";
        } else {
            isbnRow.style.display = "";
        }
    }

    toggleIsbn();
});
