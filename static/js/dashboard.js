// ==================================
// Dashboard Functions
// ==================================



function confirmDelete(message){


    return confirm(
        message ||
        "Are you sure you want to delete?"
    );


}




function toggleMenu(){


    let menu =
    document.querySelector(
        ".sidebar"
    );



    if(menu){


        menu.classList.toggle(
            "active"
        );


    }

}




// Auto refresh dashboard data

function refreshDashboard(){


    console.log(
        "Dashboard refreshed"
    );


}



setInterval(

    refreshDashboard,

    60000

);